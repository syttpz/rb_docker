#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

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
    ~BridgeNode() override;

private:
    void setupToCorelink();
    void setupFromCorelink();

    void onLocalMessage(std::shared_ptr<rclcpp::SerializedMessage> message);
    void onCorelinkMessage(const corelink::utils::json &headers, const std::vector<uint8_t> &data);

    // Hands one frame's fragments to the transport. Either inline (no pacing)
    // or via the pacer thread, depending on send.pacing_us.
    void dispatchFragments(std::vector<std::vector<uint8_t>> &&packets);
    void pacerLoop();

    // from_corelink only. See m_keepalive_s.
    void startKeepalive();

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

    // Pacing: spacing between consecutive fragments of the same frame, in
    // microseconds. 0 sends the whole frame in one tight loop (original
    // behaviour). Non-zero moves sending onto m_pacer_thread so the ROS
    // executor is never blocked by the spacing sleeps.
    int64_t m_pacing_us{0};
    std::size_t m_pacer_queue_max{0};

    std::thread m_pacer_thread;
    std::mutex m_pacer_mutex;
    std::condition_variable m_pacer_cv;
    std::deque<std::vector<uint8_t>> m_pacer_queue;   // guarded by m_pacer_mutex
    bool m_pacer_stop{false};                         // guarded by m_pacer_mutex
    std::size_t m_pacer_dropped_frames{0};            // guarded by m_pacer_mutex

    // [diag] Size accounting for buffers arriving from the transport. Off by
    // default; enable with -p diag.packet_sizes:=true when investigating
    // fragment loss that the kernel counters say is not on the network.
    bool m_diag_packet_sizes{false};
    std::size_t m_diag_packets_seen{0};
    std::map<std::size_t, std::size_t> m_diag_size_histogram;

    // NAT keepalive for receivers, in seconds (0 disables).
    //
    // corelink_client.hpp punches the return path open with exactly one empty
    // packet at on_init and never sends again. Behind a NAT that only holds an
    // unreplied UDP flow for nf_conntrack_udp_timeout (30 s by default), the
    // mapping is gone before a stream that starts later can use it -- which is
    // why a k8s pod saw every control-plane event ("new sender ... subscribing")
    // and not one byte of data. Verified: with ~1 s between receiver init and
    // the first packet the data arrives; with ~45 s nothing does.
    //
    // Re-sending that same empty packet on a timer keeps the mapping alive, so
    // it no longer matters how long after the pod starts the robot begins
    // streaming. It also covers gaps in the stream itself.
    //
    // The timer has to be stopped on shutdown rather than just left to the
    // destructor: a keepalive issued while Corelink is already tearing its
    // sockets down aborts the process ("data channel error: Operation
    // aborted", then SIGABRT from inside corelink_cpp). Cancelling from an
    // on-shutdown callback closes that window -- with keepalive_s=0 the same
    // teardown is clean, which is how the timer was identified as the cause.
    int64_t m_keepalive_s{0};
    std::atomic<bool> m_data_channel_ready{false};
    rclcpp::TimerBase::SharedPtr m_keepalive_timer;
    rclcpp::OnShutdownCallbackHandle m_shutdown_handle;

    corelink::core::network::channel_id_type m_data_channel_id{};
    rclcpp::GenericSubscription::SharedPtr m_local_subscription;
    rclcpp::GenericPublisher::SharedPtr m_local_publisher;
};

} // namespace ros2_bridge_node
