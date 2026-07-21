#include "ros2_bridge_node/bridge_node.hpp"
#include <cstring> // memcpy

namespace ros2_bridge_node
{

namespace
{

// Returns a reference to one of the static constexpr protocol objects
// (protocols::tcp/udp/websocket), not a copy. corelink's request objects
// (modify_sender_stream_request etc.) store a `const protocol &` rather
// than a copy, so this needs to keep pointing at a program-lifetime
// static, all the way through to wherever the async request completes.
// Returning by value here would hand back a temporary whose lifetime
// ends long before that -- see the same issue fixed in CorelinkTransport.
const corelink::core::network::constants::protocols::protocol &protocolFromString(const std::string &name)
{
    if (name == "tcp") return corelink::core::network::constants::protocols::tcp;
    if (name == "websocket" || name == "ws") return corelink::core::network::constants::protocols::websocket;
    // default to udp
    if (name == "udp") return corelink::core::network::constants::protocols::udp;

    throw std::invalid_argument("Invalid protocol name: " + name);
}

// "qos" is just a history depth; the local pub/sub also has to match
// whatever reliability policy the real ROS2 endpoint on the other side
// uses, or DDS refuses to match them at all (e.g. sensor topics like
// /battery_state are commonly BEST_EFFORT, while rclcpp::QoS()'s default
// is RELIABLE).
rclcpp::QoS qosFromParams(int64_t depth, const std::string &reliability)
{
    rclcpp::QoS qos(depth);
    if (reliability == "best_effort")
    {
        qos.best_effort();
    }
    else if (reliability == "reliable")
    {
        qos.reliable();
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

    const auto endpoint = declare_parameter<std::string>("corelink.endpoint", "corelink.hsrn.nyu.edu");
    const auto port = static_cast<uint16_t>(declare_parameter<int>("corelink.port", 20012));
    const auto username = declare_parameter<std::string>("corelink.username", "Testuser");
    const auto password = declare_parameter<std::string>("corelink.password", "Testpassword");
    const auto cert_path = declare_parameter<std::string>("corelink.certificate_path", "");
    const auto data_protocol_name = declare_parameter<std::string>("corelink.data_protocol", "udp");
    declare_parameter<int>("qos", 10);
    declare_parameter<std::string>("qos.reliability", "reliable");

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
    // Raw CDR passthrough: no per-message-type (de)serialization here at
    // all, see plan's "Serialization: raw CDR passthrough" section. Both
    // ends must agree on topic.type out of band (the launch/params config).
    const auto &raw = message->get_rcl_serialized_message();
    std::vector<uint8_t> data(raw.buffer, raw.buffer + raw.buffer_length);
    RCLCPP_INFO(get_logger(), "Local message on '%s' (%zu bytes), sending to Corelink.",
                m_topic_name.c_str(), data.size());
    m_transport->sendData(m_data_channel_id, std::move(data));
}

void BridgeNode::onCorelinkMessage(const corelink::utils::json & /*headers*/, const std::vector<uint8_t> &data)
{
    RCLCPP_INFO(get_logger(), "Received %zu bytes from Corelink, republishing '%s' locally.",
                data.size(), m_topic_name.c_str());
    rclcpp::SerializedMessage serialized(data.size());
    auto &raw = serialized.get_rcl_serialized_message();
    std::memcpy(raw.buffer, data.data(), data.size());
    raw.buffer_length = data.size();
    m_local_publisher->publish(serialized);
}

} // namespace ros2_bridge_node
