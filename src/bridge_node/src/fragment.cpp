#include "ros2_bridge_node/fragment.hpp"

#include <cstring> 


namespace bridge_node
{

// [frag header (9 byte)] + [corelink packet/payload]
auto pack_packet(uint32_t image_number, uint32_t sequence_number, bool is_last_fragment, const std::vector<uint8_t> &payload) -> std::vector<uint8_t>{

    
    if(payload.size() > kMaxFragmentPayload){
        throw std::length_error("Max fragment payload size exceeded");
    }else if(payload.empty()){
        throw std::domain_error("Empty payload");
    }

    // packet
    std::vector<uint8_t> packet (kFragmentHeaderSize + payload.size());
    std::memcpy(packet.data(), &image_number, 4);
    std::memcpy(packet.data() + 4, &sequence_number, 4);
    packet[8] = is_last_fragment ? 1 : 0;
    std::memcpy(packet.data() + 9, payload.data(), payload.size());

    return packet;
}

auto unpack_packet(const std::vector<uint8_t> &packet) -> std::tuple<uint32_t, uint32_t, bool, std::vector<uint8_t>>{
    //extract header 4 + 4 + 1
    FragmentHeader Frheader;

    std::memcpy(&Frheader.image_number, packet.data(), 4);
    std::memcpy(&Frheader.sequence_number, packet.data() + 4, 4);
    std::memcpy(&Frheader.is_last_fragment, packet.data()+8, 1);

    //payload 
    std::vector<uint8_t> payload(packet.begin() + kFragmentHeaderSize, packet.end());
    
    return {Frheader.image_number, Frheader.sequence_number, Frheader.is_last_fragment, payload};
}

std::optional<std::vector<uint8_t>>
FragmentReassembler::feed(const std::vector<uint8_t> &packet)
{
    //   1. unpack_packet(packet)
    //   2. store payload in m_in_progress[image].chunks[seq]; set seen_last / last_seq
    //   3. evict_stale(image)
    //   4. if seen_last && chunks.size() == last_seq + 1: concatenate chunks in
    //      sequence order, erase the entry, return the reassembled message
    //   5. otherwise return std::nullopt
    (void)packet;
    return std::nullopt;
}

void FragmentReassembler::evict_stale(uint32_t newest_image_number)
{
    // update m_newest_image_number; erase any in-progress frame whose
    // image_number < newest - kReassemblyWindow (mind unsigned underflow).
    (void)newest_image_number;
}

} 
