#ifndef LOCALDREAM_S24U_LONG_PROMPT_CHUNKING_HPP
#define LOCALDREAM_S24U_LONG_PROMPT_CHUNKING_HPP

namespace localdream::s24u154 {

inline constexpr int kClipSequenceLength = 77;
inline constexpr int kClipContentLength = 75;
inline constexpr int kLegacySequenceLength = 77;
inline constexpr int kLongSequenceLength = 154;

inline constexpr bool isSupportedSequenceLength(int n) {
  return n == kLegacySequenceLength || n == kLongSequenceLength;
}

inline constexpr int chunkCountForSequenceLength(int n) {
  return isSupportedSequenceLength(n) ? n / kClipSequenceLength : 0;
}

inline constexpr int contentCapacityForSequenceLength(int n) {
  return chunkCountForSequenceLength(n) * kClipContentLength;
}

inline constexpr int chunkForContentIndex(int content_index) {
  return content_index < 0 ? -1 : content_index / kClipContentLength;
}

inline constexpr int outputSlotForContentIndex(int content_index) {
  if (content_index < 0) return -1;
  const int chunk = chunkForContentIndex(content_index);
  const int local = content_index % kClipContentLength;
  return chunk * kClipSequenceLength + 1 + local;
}

inline constexpr int localPositionForSlot(int slot) {
  return slot < 0 ? -1 : slot % kClipSequenceLength;
}

inline constexpr int usedChunkCount(int content_tokens) {
  return content_tokens <= kClipContentLength ? 1 : 2;
}

inline constexpr int eosSlotForChunk(int chunk, int used_content_tokens) {
  const int clamped = used_content_tokens < 0
                          ? 0
                          : (used_content_tokens > kClipContentLength
                                 ? kClipContentLength
                                 : used_content_tokens);
  return chunk * kClipSequenceLength + 1 + clamped;
}

}  // namespace localdream::s24u154

#endif
