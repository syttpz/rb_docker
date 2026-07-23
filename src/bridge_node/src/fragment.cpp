#include "fragment.hpp"
#include "bridge_node.hpp"

/**
* Pack orignal packet payload (rvref?) with fragment attributes,
*
*/
auto pack_packet(uint32_t sequence_number, uint32_t image_number, bool is_last_fragment, const std::vector<uint8_t>& payload) -> std::vector<uint8_t>{
    reliable_udp_header header;
    header.sequence_number = sequence_number;
    header.image_number = image_number;
    header.is_last_fragment = is_last_fragment ? 1 : 0;

    std::vector<uint8_t> packet(sizeof(reliable_udp_header) + payload.size());
    //copy header data to packet
    memcpy(packet.data(), &header, sizeof(reliable_udp_header));
    //concatenate payload
    memcpy(packet.data() + sizeof(reliable_udp_header), payload.data(), payload.size());

    return packet;
}

auto unpack_packet(const std::vector<uint8_t>& packet) -> std::tuple<uint32_t, uint32_t, bool, std::vector<uint8_t>> {
    reliable_udp_header header;
    std::vector<uint8_t> unpacked_payload (sizeof(packet) - sizeof(header));

    std::size_t offset = 0;

    memcpy(&header.sequence_number, packet.data() + offset);
    offset += sizeof(header.sequence_number);

    memcpy(&header.image_number, packet.data() + offset);
    offset += sizeof(header.image_number);

    memcpy(&header.is_last_fragment, packet.data() + offset);
    offset += sizeof(header.is_last_fragment);

    memcpy(&unpacked_payload, packet.data() + offset);

    return {
        header,
        std::move(unpacked_payload);
    }

}


class ReliableUDP {
public:
    ReliableUDP(uint16_t port, core::network::channel_id_type channel_id){
        //channel_id from bridge node?
    }
    ~ReliableUDP();

    bool send_reliable_udp_packet(const std::vector<uint8_t>& payload, uint32_t sequence_number, uint32_t image_number, bool is_last_fragment);
    bool receive_reliable_udp_packet(std::vector<uint8_t>& payload, uint32_t& sequence_number, uint32_t& image_number, bool& is_last_fragment);
private:
    std::unique_ptr<corelink::Socket> socket_;
    uint16_t port_;
};
