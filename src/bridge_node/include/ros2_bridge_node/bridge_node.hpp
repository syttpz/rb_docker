#pragma once

#include <chrono>
#include <map>
#include <memory>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp/generic_publisher.hpp>
#include <rclcpp/generic_subscription.hpp>

#include "ros2_bridge_node/corelink_transport.hpp"
#include "ros2_bridge_node/fragment.hpp"

namespace ros2_bridge_node
{

// First-cut ROS2 <-> Corelink bridge node.
//
// Bridges exactly ONE local ROS2 topic to/from ONE Corelink stream
// (workspace + stream_type == topic name), in exactly one direction
// per node instance. This is deliberately the smallest possible thing
// that proves the end-to-end path (see the incremental build order in
// the plan: single hardcoded/parameterized topic before generalizing
// to a config-driven multi-topic manager).
//
// "to_corelink"   : subscribes locally (GenericSubscription), forwards
//                   raw serialized bytes to a Corelink sender stream.
// "from_corelink" : creates a Corelink receiver stream, republishes
//                   incoming bytes locally (GenericPublisher).
class BridgeNode : public rclcpp::Node
{
public:
    BridgeNode();

private:
    void setupToCorelink();
    void setupFromCorelink();

    void onLocalMessage(std::shared_ptr<rclcpp::SerializedMessage> message);
    void onCorelinkMessage(const corelink::utils::json &headers, const std::vector<uint8_t> &data);

    std::string m_topic_name;
    std::string m_topic_type;
    std::string m_direction;
    std::string m_workspace;

    std::unique_ptr<CorelinkTransport> m_transport;

    // Fragmentation: outgoing frames are sliced into MTU-sized packets,
    // incoming packets are reassembled back into whole frames. Only ever
    // touched from Corelink's single stream-callback thread.
    bridge_node::Slicer m_slicer;
    bridge_node::Reassembler m_reassembler;

    // Outgoing rate cap, in Hz. 0 disables throttling (forward every message).
    // Lets a high-rate source (e.g. a 15Hz camera) be bridged at a lower rate
    // without touching the source node, so the link budget can be swept from
    // the command line.
    double m_max_rate_hz{0.0};
    std::chrono::steady_clock::time_point m_last_forwarded_at{};

    // [diag] Size accounting for buffers arriving from the transport. Off by
    // default; enable with -p diag.packet_sizes:=true when investigating
    // fragment loss that the kernel counters say is not on the network.
    bool m_diag_packet_sizes{false};
    std::size_t m_diag_packets_seen{0};
    std::map<std::size_t, std::size_t> m_diag_size_histogram;

    corelink::core::network::channel_id_type m_data_channel_id{};
    rclcpp::GenericSubscription::SharedPtr m_local_subscription;
    rclcpp::GenericPublisher::SharedPtr m_local_publisher;
};

} // namespace ros2_bridge_node
