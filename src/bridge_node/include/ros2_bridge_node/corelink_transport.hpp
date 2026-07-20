#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "corelink_all.hpp"

namespace ros2_bridge_node
{

// Thin wrapper around corelink::client::corelink_classic_client.
// Hides the connect -> authenticate -> create_sender/create_receiver
// async request/response plumbing behind plain callbacks so the ROS2
// node code doesn't need to touch Corelink's request()/completion_handler
// machinery directly.
class CorelinkTransport
{
public:
    using ReadyCallback = std::function<void(bool ok, const std::string &message)>;
    using StreamReadyCallback = std::function<void(corelink::core::network::channel_id_type channel_id)>;
    using ReceiveCallback = std::function<void(
            const corelink::utils::json &headers,
            const std::vector<uint8_t> &data)>;

    // control_protocol is taken by reference (not copied) because
    // corelink_client_connection_info::protocol is itself a reference
    // member (clvref<protocol> = const protocol&) -- it stores a
    // reference to whatever protocol object the caller passes, not a
    // copy. Taking it by value here would create a local copy that dies
    // when this constructor returns, leaving that downstream reference
    // dangling. Callers must pass one of the static constexpr protocol
    // objects (protocols::websocket / tcp / udp), which live for the
    // whole program, so the reference stays valid.
    CorelinkTransport(
            std::string endpoint,
            uint16_t port,
            std::string username,
            std::string password,
            std::string certificate_path,
            const corelink::core::network::constants::protocols::protocol &control_protocol);

    // Connects the control channel and authenticates. on_ready is invoked
    // once (from Corelink's internal event-loop thread, not the caller's
    // thread) with ok=true once authentication succeeds, or ok=false on
    // any failure along the way.
    void connect(ReadyCallback on_ready);

    // Creates a sender stream (workspace/stream_type == ROS2 topic name by
    // convention) using the given data-channel protocol. on_ready fires
    // once the underlying data channel socket is actually established and
    // returns the data_channel_id to pass to sendData().
    // data_protocol is a reference for the same reason as the constructor's
    // control_protocol: modify_sender_stream_request/modify_data_stream_request_base
    // store a `const protocol &`, not a copy. Pass one of the static
    // constexpr protocol objects.
    void createSender(
            const std::string &workspace,
            const std::string &stream_type,
            const corelink::core::network::constants::protocols::protocol &data_protocol,
            StreamReadyCallback on_ready);

    // Creates a receiver stream subscribing to stream_type. on_data fires
    // (from Corelink's internal thread) for every message received.
    void createReceiver(
            const std::string &workspace,
            const std::string &stream_type,
            const corelink::core::network::constants::protocols::protocol &data_protocol,
            ReceiveCallback on_data,
            StreamReadyCallback on_ready);

    // Fire-and-forget send on an already-established sender data channel.
    void sendData(
            corelink::core::network::channel_id_type data_channel_id,
            std::vector<uint8_t> data);

private:
    corelink::client::corelink_classic_client m_client;
    corelink::client::corelink_client_connection_info m_connection_info;
    corelink::core::network::channel_id_type m_control_channel_id{};
};

} // namespace ros2_bridge_node
