using System.IO;
using System.Text;
using System.Text.Json;

namespace MLLM.Workbench.Desktop.Services.Conversation;

public sealed record OpenAiSseReadResult(
    string ResponseText,
    int? CompletionTokens,
    bool SawDone);

public sealed class OpenAiSseReader
{
    public async Task<OpenAiSseReadResult> ReadAsync(
        Stream stream,
        IProgress<ConversationDelta>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(stream);

        using var reader = new StreamReader(
            stream,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true),
            detectEncodingFromByteOrderMarks: true,
            bufferSize: 1024,
            leaveOpen: true);
        var response = new StringBuilder();
        var eventData = new StringBuilder();
        var sawJsonEvent = false;
        var sawDone = false;
        int? completionTokens = null;

        while (true)
        {
            var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
            if (line is null)
            {
                if (eventData.Length > 0)
                    ProcessEvent(eventData.ToString());
                break;
            }

            if (line.Length == 0)
            {
                if (eventData.Length == 0) continue;
                if (ProcessEvent(eventData.ToString())) break;
                eventData.Clear();
                continue;
            }

            if (line.StartsWith(':')) continue;
            if (!line.StartsWith("data:", StringComparison.Ordinal)) continue;
            if (eventData.Length > 0) eventData.Append('\n');
            eventData.Append(line.AsSpan(5).TrimStart());
        }

        if (!sawJsonEvent)
            throw ProtocolError("OpenAI stream ended without a valid JSON event.");

        return new OpenAiSseReadResult(response.ToString(), completionTokens, sawDone);

        bool ProcessEvent(string data)
        {
            if (string.Equals(data.Trim(), "[DONE]", StringComparison.Ordinal))
            {
                sawDone = true;
                return true;
            }

            try
            {
                using var document = JsonDocument.Parse(data);
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                    throw ProtocolError("OpenAI stream event must be a JSON object.");

                sawJsonEvent = true;
                if (root.TryGetProperty("usage", out var usage) && usage.ValueKind != JsonValueKind.Null)
                {
                    if (usage.ValueKind != JsonValueKind.Object ||
                        !usage.TryGetProperty("completion_tokens", out var tokenElement) ||
                        !tokenElement.TryGetInt32(out var parsedTokens) ||
                        parsedTokens < 0)
                    {
                        throw ProtocolError("OpenAI stream usage.completion_tokens is invalid.");
                    }
                    completionTokens = parsedTokens;
                }

                if (!root.TryGetProperty("choices", out var choices)) return false;
                if (choices.ValueKind != JsonValueKind.Array)
                    throw ProtocolError("OpenAI stream choices must be an array.");

                foreach (var choice in choices.EnumerateArray())
                {
                    if (choice.ValueKind != JsonValueKind.Object ||
                        !choice.TryGetProperty("index", out var indexElement) ||
                        !indexElement.TryGetInt32(out var index) ||
                        index != 0)
                    {
                        throw ProtocolError("OpenAI stream contains a non-primary or invalid choice.");
                    }

                    if (!choice.TryGetProperty("delta", out var delta) || delta.ValueKind != JsonValueKind.Object)
                        continue;
                    if (!delta.TryGetProperty("content", out var content) || content.ValueKind == JsonValueKind.Null)
                        continue;
                    if (content.ValueKind != JsonValueKind.String)
                        throw ProtocolError("OpenAI stream delta content must be a string.");

                    var text = content.GetString();
                    if (string.IsNullOrEmpty(text)) continue;
                    response.Append(text);
                    progress?.Report(new ConversationDelta(text));
                }

                return false;
            }
            catch (ConversationProtocolException)
            {
                throw;
            }
            catch (JsonException ex)
            {
                throw ProtocolError("OpenAI stream contained malformed JSON.", ex);
            }
        }
    }

    private static ConversationProtocolException ProtocolError(string message, Exception? inner = null) =>
        new("STREAM_PROTOCOL_ERROR", message, inner);
}
