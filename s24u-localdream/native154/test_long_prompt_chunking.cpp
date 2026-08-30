#include <cassert>
#include <iostream>

#include "LongPromptChunking.hpp"

using namespace localdream::s24u154;

int main() {
  assert(isSupportedSequenceLength(77));
  assert(isSupportedSequenceLength(154));
  assert(!isSupportedSequenceLength(153));
  assert(!isSupportedSequenceLength(231));

  assert(contentCapacityForSequenceLength(77) == 75);
  assert(contentCapacityForSequenceLength(154) == 150);

  assert(outputSlotForContentIndex(0) == 1);
  assert(outputSlotForContentIndex(74) == 75);
  assert(outputSlotForContentIndex(75) == 78);
  assert(outputSlotForContentIndex(149) == 152);

  assert(localPositionForSlot(0) == 0);
  assert(localPositionForSlot(76) == 76);
  assert(localPositionForSlot(77) == 0);
  assert(localPositionForSlot(153) == 76);

  assert(usedChunkCount(0) == 1);
  assert(usedChunkCount(75) == 1);
  assert(usedChunkCount(76) == 2);
  assert(usedChunkCount(150) == 2);

  assert(eosSlotForChunk(0, 0) == 1);
  assert(eosSlotForChunk(0, 75) == 76);
  assert(eosSlotForChunk(1, 0) == 78);
  assert(eosSlotForChunk(1, 75) == 153);

  std::cout << "S24U_154_LAYOUT=PASS\n";
  return 0;
}
