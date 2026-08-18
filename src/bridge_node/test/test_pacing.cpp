#include "ros2_bridge_node/pacing.hpp"

#include <cassert>
#include <stdexcept>

int main()
{
    using ros2_bridge_node::calculatePacingUs;

    // Weekly update examples: 6 Hz, 10% of each frame reserved.
    assert(calculatePacingUs(6.0, 0.10, 58) == 2586);
    assert(calculatePacingUs(6.0, 0.10, 39) == 3846);

    // The actual serialized size may change the fragment count per frame.
    assert(calculatePacingUs(15.0, 0.10, 1) == 60000);

    bool rejected = false;
    try { (void)calculatePacingUs(0.0, 0.10, 58); }
    catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);

    rejected = false;
    try { (void)calculatePacingUs(6.0, 1.0, 58); }
    catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);
}
