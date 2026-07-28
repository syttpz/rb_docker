#include "ros2_bridge_node/bridge_node.hpp"

#include <cstring> // memcpy

namespace ros2_bridge_node
{

namespace
{


const corelink::core::network::constants::protocols::protocol &protocolFromString(const std::string &name)
{
    if (name == "tcp") return corelink::core::network::constants::protocols::tcp;
    if (name == "websocket" || name == "ws") return corelink::core::network::constants::protocols::websocket;
    // default to udp
    if (name == "udp") return corelink::core::network::constants::protocols::udp;

    throw std::invalid_argument("Invalid protocol name: " + name);
}


rclcpp::QoS qosFromParams(int64_t depth, const std::string &reliability)
{
    rclcpp::QoS qos(depth);
    if (reliability == "best_effort")
    {
        qos.best_effort();
    }
    else if (reliability == "reliable")
    {
        qos.reliable(); //history depth
    }
    else
    {
        throw std::invalid_argument("Invalid qos.reliability: " + reliability + " (expected 'reliable' or 'best_effort')");
    }
    return qos;
}

}


// create ros2_bridge_node  
BridgeNode::BridgeNode() : rclcpp::Node("ros2_bridge_node")
{
    // topicname = streamtype
    m_topic_name = declare_parameter<std::string>("topic.name", "/chatter");
    m_topic_type = declare_parameter<std::string>("topic.type", "std_msgs/msg/String");
    m_direction = declare_parameter<std::string>("topic.direction", "to_corelink");
    m_workspace = declare_parameter<std::string>("corelink.workspace", "Chalktalk");

    const auto endpoint = declare_parameter<std::string>("corelink.endpoint", "corelink.hpc.nyu.edu");
    const auto port = static_cast<uint16_t>(declare_parameter<int>("corelink.port", 20012));
    const auto username = declare_parameter<std::string>("corelink.username", "Testuser");
    const auto password = declare_parameter<std::string>("corelink.password", "Testpassword");
    const auto cert_path = declare_parameter<std::string>("corelink.certificate_path", "");
    const auto data_protocol_name = declare_parameter<std::string>("corelink.data_protocol", "udp");
    declare_parameter<int>("qos", 10);
    declare_parameter<std::string>("qos.reliability", "reliable");
    m_max_rate_hz = declare_parameter<double>("topic.max_rate", 0.0);
    m_diag_packet_sizes = declare_parameter<bool>("diag.packet_sizes", false);

    if (m_workspace.empty())
    {
        RCLCPP_FATAL(get_logger(), "E: workspace is required");
        throw std::runtime_error("workspace not set");
    }
    if (m_direction != "to_corelink" && m_direction != "from_corelink")
    {
        RCLCPP_FATAL(get_logger(), "E: invalid direction");
        throw std::runtime_error("invalid direction");
    }


    m_transport = std::make_unique<CorelinkTransport>(
            endpoint, port, username, password, cert_path,
            // note: auth protocol is always websocket, data protocol can be udp/tcp/ws
            corelink::core::network::constants::protocols::websocket);  

    RCLCPP_INFO(get_logger(), "Connecting to Corelink Server at %s:%u ...", endpoint.c_str(), port);


    // Connect to Corelink and authenticate. 
    m_transport->connect(
            [this](bool ok, const std::string &message)
            {
                if (!ok)
                {
                    RCLCPP_FATAL(get_logger(), "Corelink connect failed: %s", message.c_str());
                    return;
                }
                RCLCPP_INFO(get_logger(), "Corelink authenticated. Setting up '%s' (%s)...",
                            m_topic_name.c_str(), m_direction.c_str());

                if (m_direction == "to_corelink")
                {
                    setupToCorelink();
                }
                else
                {
                    setupFromCorelink();
                }
            });
}

void BridgeNode::setupToCorelink()
{
    const auto data_protocol_name = get_parameter("corelink.data_protocol").as_string();
    const auto qos = qosFromParams(get_parameter("qos").as_int(), get_parameter("qos.reliability").as_string());
    const auto &data_protocol = protocolFromString(data_protocol_name);

    m_transport->createSender(
            m_workspace,
            m_topic_name,
            data_protocol,
            [this, qos](corelink::core::network::channel_id_type channel_id)
            {
                m_data_channel_id = channel_id;
                RCLCPP_INFO(get_logger(), "Corelink sender stream ready (channel %llu). Subscribing to '%s' locally.",
                            static_cast<unsigned long long>(channel_id), m_topic_name.c_str());

                m_local_subscription = create_generic_subscription( // knows the topic type at run time
                        m_topic_name,
                        m_topic_type,
                        qos,
                        [this](std::shared_ptr<rclcpp::SerializedMessage> message)
                        {
                            onLocalMessage(message);
                        });
            });
}

void BridgeNode::setupFromCorelink()
{
    const auto data_protocol_name = get_parameter("corelink.data_protocol").as_string();
    const auto &data_protocol = protocolFromString(data_protocol_name);
    const auto qos = qosFromParams(get_parameter("qos").as_int(), get_parameter("qos.reliability").as_string());

    m_local_publisher = create_generic_publisher(m_topic_name, m_topic_type, qos);

    m_transport->createReceiver(
            m_workspace,
            m_topic_name,
            data_protocol,
            [this](const corelink::utils::json &headers, const std::vector<uint8_t> &data)
            {
                onCorelinkMessage(headers, data);
            },
            [this](corelink::core::network::channel_id_type channel_id)
            {
                m_data_channel_id = channel_id;
                RCLCPP_INFO(get_logger(), "Corelink receiver stream ready (channel %llu). Publishing '%s' locally.",
                            static_cast<unsigned long long>(channel_id), m_topic_name.c_str());
            });
}

void BridgeNode::onLocalMessage(std::shared_ptr<rclcpp::SerializedMessage> message)
{
    // Drop messages that arrive faster than topic.max_rate. Steady clock, so a
    // simulated or stepped /clock can't stall the link or let it burst.
    if (m_max_rate_hz > 0.0)
    {
        const auto now = std::chrono::steady_clock::now();
        const auto min_gap = std::chrono::duration<double>(1.0 / m_max_rate_hz);
        if (m_last_forwarded_at.time_since_epoch().count() != 0 &&
            now - m_last_forwarded_at < std::chrono::duration_cast<std::chrono::steady_clock::duration>(min_gap))
        {
            return;
        }
        m_last_forwarded_at = now;
    }

    // Raw CDR -> one or more fragment packets. Small frames still produce a
    // single (last) fragment so the receiver's reassembly path is uniform.
    const auto &raw = message->get_rcl_serialized_message();
    auto packets = m_slicer.slice(raw.buffer, raw.buffer_length);

    RCLCPP_INFO(get_logger(), "Local message on '%s' (%zu bytes) -> %zu fragment(s), sending to Corelink.",
                m_topic_name.c_str(), static_cast<std::size_t>(raw.buffer_length), packets.size());

    for (auto &packet : packets)
    {
        m_transport->sendData(m_data_channel_id, std::move(packet));
    }
}

void BridgeNode::onCorelinkMessage(const corelink::utils::json & /*headers*/, const std::vector<uint8_t> &data)
{
    // [diag] Every buffer handed up by the transport should be exactly one
    // fragment as it left the sender. Anything else means the transport
    // coalesced or truncated datagrams before we ever saw them, which no
    // amount of reassembly logic on our side can recover.
    if (m_diag_packet_sizes)
    {
        ++m_diag_packets_seen;
        m_diag_size_histogram[data.size()]++;
        if (data.size() % (bridge_node::kFragmentHeaderSize + bridge_node::kMaxFragmentPayload) == 0 &&
            data.size() > bridge_node::kFragmentHeaderSize + bridge_node::kMaxFragmentPayload)
        {
            RCLCPP_WARN(get_logger(), "[diag] coalesced buffer: %zu bytes (= %zu fragments glued together)",
                        data.size(), data.size() / (bridge_node::kFragmentHeaderSize + bridge_node::kMaxFragmentPayload));
        }
        if (m_diag_packets_seen % 1000 == 0)
        {
            std::string hist;
            for (const auto &[size, count] : m_diag_size_histogram)
            {
                hist += " " + std::to_string(size) + "x" + std::to_string(count);
            }
            RCLCPP_INFO(get_logger(), "[diag] %zu buffers received, sizes:%s",
                        m_diag_packets_seen, hist.c_str());
        }
    }

    // Feed the fragment into the reassembler; only publish once a whole frame
    // has been reconstructed. This runs on Corelink's event loop thread, where
    // an escaping exception would take the process down, so a malformed buffer
    // (shorter than a fragment header) is logged and dropped instead.
    std::optional<std::vector<uint8_t>> frame;
    try
    {
        frame = m_reassembler.feed(data);
    }
    catch (const std::exception &e)
    {
        RCLCPP_WARN(get_logger(), "Dropping malformed buffer of %zu bytes: %s", data.size(), e.what());
        return;
    }
    if (!frame)
    {
        return;
    }

    RCLCPP_INFO(get_logger(), "Reassembled %zu bytes from Corelink, republishing '%s' locally.",
                frame->size(), m_topic_name.c_str());
    rclcpp::SerializedMessage serialized(frame->size());
    auto &raw = serialized.get_rcl_serialized_message();
    std::memcpy(raw.buffer, frame->data(), frame->size());
    raw.buffer_length = frame->size();
    m_local_publisher->publish(serialized);
}

} // namespace ros2_bridge_node
