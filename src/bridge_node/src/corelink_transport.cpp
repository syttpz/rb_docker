#include "ros2_bridge_node/corelink_transport.hpp"

#include <cstdio>

namespace ros2_bridge_node
{

CorelinkTransport::CorelinkTransport(
        std::string endpoint,
        uint16_t port,
        std::string username,
        std::string password,
        std::string certificate_path,
        const corelink::core::network::constants::protocols::protocol &control_protocol)
        : m_connection_info(control_protocol)
{
    m_connection_info
            .set_endpoint(endpoint)
            .set_port_number(port)
            .set_username(username)
            .set_password(password)
            .set_certificate_path(certificate_path);
}

void CorelinkTransport::connect(ReadyCallback on_ready)
{
    if (!m_client.init_protocols())
    {
        on_ready(false, "Failed to initialize Corelink protocols");
        return;
    }

    // Captured by value: on_ready must stay alive across the async
    // control-channel-connect -> authenticate chain below.
    m_control_channel_id = m_client.add_control_channel(
            m_connection_info,
            [on_ready](corelink::core::network::channel_id_type, const std::string &message)
            {
                on_ready(false, "Control channel error: " + message);
            },
            [this, on_ready](corelink::core::network::channel_id_type channel_id)
            {
                // Control channel connected. Now authenticate.
                m_client.request(
                        channel_id,
                        corelink::client::corelink_functions::authenticate,
                        std::make_shared<corelink::client::request_response::requests::authenticate_client_request>(
                                m_connection_info.username,
                                m_connection_info.password),
                        [on_ready](
                                corelink::core::network::channel_id_type,
                                const std::string &msg,
                                std::shared_ptr<corelink::client::request_response::responses::corelink_server_response_base> response)
                        {
                            if (response->status_code != 0)
                            {
                                on_ready(false, "Authentication failed: " + response->message + " " + msg);
                                return;
                            }
                            on_ready(true, "");
                        });
            },
            [](corelink::core::network::channel_id_type)
            {
                // Control channel dropped. The caller finds out about this
                // indirectly: any subsequent request()/send_data() calls on
                // this transport will simply fail. Reconnect handling is
                // intentionally left out of this first prototype.
            });
}

void CorelinkTransport::createSender(
        const std::string &workspace,
        const std::string &stream_type,
        const corelink::core::network::constants::protocols::protocol &data_protocol,
        StreamReadyCallback on_ready)
{
    auto request = std::make_shared<
            corelink::client::request_response::requests::modify_sender_stream_request>(data_protocol);
    request->workspace = workspace;
    request->stream_type = stream_type;
    request->meta = "ros2_bridge_node sender";
    request->alert = true;
    request->echo = false;
    request->on_init = [on_ready](corelink::core::network::channel_id_type channel_id)
    {
        on_ready(channel_id);
    };
    request->on_error = [](corelink::core::network::channel_id_type channel_id, const std::string &err)
    {
        std::fprintf(stderr, "[diag] sender data channel %llu error: %s\n",
                static_cast<unsigned long long>(channel_id), err.c_str());
    };
    request->on_send = [](corelink::core::network::channel_id_type channel_id, size_t bytes_sent)
    {
        std::fprintf(stderr, "[diag] sender data channel %llu confirmed %zu bytes sent\n",
                static_cast<unsigned long long>(channel_id), bytes_sent);
    };

    m_client.request(
            m_control_channel_id,
            corelink::client::corelink_functions::create_sender,
            request,
            [](corelink::core::network::channel_id_type,
               const std::string &,
               std::shared_ptr<corelink::client::request_response::responses::corelink_server_response_base>)
            {
                // The data channel itself isn't ready yet here -- see
                // on_init above. This just confirms the server accepted
                // the create_sender request.
            });
}

void CorelinkTransport::createReceiver(
        const std::string &workspace,
        const std::string &stream_type,
        const corelink::core::network::constants::protocols::protocol &data_protocol,
        ReceiveCallback on_data,
        StreamReadyCallback on_ready)
{
    // create_receiver alone does NOT make data start flowing: matching
    // workspace/stream_type on a create_receiver call only puts this
    // client on the server's radar for that type. The server separately
    // pushes a "server_callback_on_update" event on the control channel
    // whenever a sender with a matching stream_type shows up, and the
    // client has to explicitly subscribe() to that sender's stream_id
    // before the server starts forwarding its data to us. Without this,
    // create_receiver's on_init still fires (the local data channel socket
    // is real) but on_receive never does. Confirmed against the reference
    // client flow in data_center_robot's CorelinkInterface::addOnUpdateHandler.
    m_client.request(
            m_control_channel_id,
            corelink::client::corelink_functions::server_callback_on_update,
            nullptr,
            [this, stream_type](
                    corelink::core::network::channel_id_type channel_id,
                    const std::string &,
                    std::shared_ptr<corelink::client::request_response::responses::corelink_server_response_base> response)
            {
                if (response->status_code != 0)
                {
                    std::fprintf(stderr, "[diag] update callback status_code=%d\n", response->status_code);
                    return;
                }
                auto update = std::static_pointer_cast<
                        corelink::client::request_response::responses::server_cb_on_update_response>(response);
                std::fprintf(stderr,
                        "[diag] server_callback_on_update: type='%s' (want '%s') receiver_id=%lld stream_id=%lld user='%s' meta='%s'\n",
                        update->type.c_str(), stream_type.c_str(),
                        static_cast<long long>(update->receiver_id), static_cast<long long>(update->stream_id),
                        update->user.c_str(), update->meta.c_str());
                if (update->type != stream_type)
                {
                    return; // some other stream_type under the same workspace
                }

                m_client.request(
                        channel_id,
                        corelink::client::corelink_functions::subscribe,
                        std::make_shared<corelink::client::request_response::requests::modify_stream_subscription_request>(
                                update->receiver_id,
                                std::vector<corelink::client::constants::corelink_stream_id_type>{update->stream_id}),
                        [](corelink::core::network::channel_id_type,
                           const std::string &,
                           std::shared_ptr<corelink::client::request_response::responses::corelink_server_response_base> sub_response)
                        {
                            std::fprintf(stderr, "[diag] subscribe response status_code=%d\n", sub_response->status_code);
                            // Data starts arriving on on_receive (or doesn't,
                            // on failure) -- nothing to branch on here.
                        });
            });

    auto request = std::make_shared<
            corelink::client::request_response::requests::modify_receiver_stream_request>(data_protocol);
    request->workspace = workspace;
    request->stream_type = stream_type;
    request->meta = "ros2_bridge_node receiver";
    request->alert = true;
    request->echo = false;
    request->on_init = [on_ready](corelink::core::network::channel_id_type channel_id)
    {
        on_ready(channel_id);
    };
    request->on_error = [](corelink::core::network::channel_id_type channel_id, const std::string &err)
    {
        std::fprintf(stderr, "[diag] receiver data channel %llu error: %s\n",
                static_cast<unsigned long long>(channel_id), err.c_str());
    };
    request->on_receive = [on_data](
            corelink::core::network::channel_id_type,
            const corelink::client::constants::corelink_stream_id_type &,
            const corelink::utils::json &headers,
            std::vector<uint8_t> data)
    {
        on_data(headers, data);
    };

    m_client.request(
            m_control_channel_id,
            corelink::client::corelink_functions::create_receiver,
            request,
            [](corelink::core::network::channel_id_type,
               const std::string &,
               std::shared_ptr<corelink::client::request_response::responses::corelink_server_response_base>)
            {
                // Same as createSender: real readiness is on_init above.
            });
}

void CorelinkTransport::sendData(
        corelink::core::network::channel_id_type data_channel_id,
        std::vector<uint8_t> data)
{
    corelink::utils::json headers;
    m_client.send_data(data_channel_id, std::move(data), std::move(headers));
}

} // namespace ros2_bridge_node
