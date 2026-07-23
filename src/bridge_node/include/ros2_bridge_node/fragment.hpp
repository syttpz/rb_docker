/**
 * @author: syttpz
 * @file: fragment.hpp
 * @brief: reliable udp fragment header, ACK, reliable udp receiver class, and dynamic buffer based on message size
*/
#pragma once

#include <csocket>
#include <cstdint>
#include <chrono>
#include <functional>
#include <memory>

#include "corelink_all.hpp"

/**
Further compacted
32 bit - 4 byte header
10 bit - sequence_number

*/
struct reliable_udp_header {
    uint32_t sequence_number;
    uint32_t image_number;
    uint8_t is_last_fragment;
};

auto pack_packet(uint32_t sequence_number, uint32_t image_number, bool is_last_fragment, const std::vector<uint8_t>& payload) -> std::vector<uint8_t>;

auto unpack_packet(const std::vector<uint8_t>& packet) -> std::tuple<uint32_t, uint32_t, bool, std::vector<uint8_t>>;

class ReliableUDPReceiver {
public:
    ReliableUDPReceiver(uint16_t port);
    ~ReliableUDPReceiver();

    bool send_reliable_udp_packet(const std::vector<uint8_t>& payload, uint32_t sequence_number, uint32_t image_number, bool is_last_fragment);
    bool receive_reliable_udp_packet(std::vector<uint8_t>& payload, uint32_t& sequence_number, uint32_t& image_number, bool& is_last_fragment);
private:
    std::unique_ptr<corelink::Socket> socket_;
    uint16_t port_;
};

