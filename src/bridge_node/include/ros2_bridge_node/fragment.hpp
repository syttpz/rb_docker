/**
 * @brief: enables image/large size data (> MTU) to be transmissioned through fragmentation
 *
 *  sender:   onLocalMessage(entire frame) -> [slicer] -> sendData N times (channel, bytes)
 *  receiver: onCorelinkMessage(fragment)  -> [reassembler] -> publish once a frame is whole
 *
*/
#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <tuple>
#include <vector>
#include <stdexcept>


namespace bridge_node
{
struct FragmentHeader {
    uint32_t image_number;      
    uint32_t sequence_number;   
    uint8_t is_last_fragment;   
};

// 9 byte header size
constexpr std::size_t kFragmentHeaderSize = 9;

// max payload byte
constexpr std::size_t kMaxFragmentPayload = 16000;

// MTU
constexpr std::size_t MTU = 20000; //20 KB get the MTU dynamically?


auto pack_packet(uint32_t image_number, uint32_t sequence_number, bool is_last_fragment,
                 const std::vector<uint8_t>& payload) -> std::vector<uint8_t>;

auto unpack_packet(const std::vector<uint8_t>& packet)
        -> std::tuple<uint32_t, uint32_t, bool, std::vector<uint8_t>>;



class Slicer{
public:
    std::vector<std::vector<uint8_t>> slice(const uint8_t* data, std::size_t len);

private:
    uint32_t cur_image_num{0}; //++ on slice
};


class Reassembler {
public:
    // feeds one received fragment
    std::optional<std::vector<uint8_t>> feed(const std::vector<uint8_t>& packet);

private:
    struct PartialFrame {
        std::map<uint32_t, std::vector<uint8_t>> chunks;  // stores sequence
        bool seen_last{false};
        uint32_t last_seq{0};                            
    };

    void evict_stale(uint32_t newest_image_number);

    std::map<uint32_t, PartialFrame> m_in_progress;
    uint32_t m_newest_image_number{0};


    static constexpr uint32_t kReassemblyWindow = 4;
};

} 
