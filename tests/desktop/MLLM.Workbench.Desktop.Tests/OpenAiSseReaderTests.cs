using System.IO;
using System.Text;
using MLLM.Workbench.Desktop.Services.Conversation;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class OpenAiSseReaderTests
{
    [Fact]
    public async Task Fragmented_primary_choice_frames_emit_content_capture_usage_and_stop_at_done()
    {
        const string sse =
            "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"你\"}}]}\n\n" +
            "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"好\"}}]}\n\n" +
            "data: {\"choices\":[],\"usage\":{\"completion_tokens\":2}}\n\n" +
            "data: [DONE]\n\n";
        await using var source = new FragmentedReadStream(Encoding.UTF8.GetBytes(sse), 3);
        var deltas = new List<string>();

        var result = await new OpenAiSseReader().ReadAsync(
            source,
            new InlineProgress<ConversationDelta>(item => deltas.Add(item.Content)),
            CancellationToken.None);

        Assert.Equal(["你", "好"], deltas);
        Assert.Equal("你好", result.ResponseText);
        Assert.Equal(2, result.CompletionTokens);
        Assert.True(result.SawDone);
    }

    [Fact]
    public async Task Clean_end_of_stream_after_valid_content_is_accepted_without_fabricating_usage()
    {
        const string sse = "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"ok\"}}]}\n\n";
        await using var source = new MemoryStream(Encoding.UTF8.GetBytes(sse));

        var result = await new OpenAiSseReader().ReadAsync(source, null, CancellationToken.None);

        Assert.Equal("ok", result.ResponseText);
        Assert.Null(result.CompletionTokens);
        Assert.False(result.SawDone);
    }

    [Theory]
    [InlineData("data: {not-json}\n\n")]
    [InlineData("data: {\"choices\":[{\"index\":1,\"delta\":{\"content\":\"wrong\"}}]}\n\n")]
    [InlineData("data: [DONE]\n\n")]
    public async Task Malformed_nonprimary_or_empty_streams_fail_closed(string sse)
    {
        await using var source = new MemoryStream(Encoding.UTF8.GetBytes(sse));

        var error = await Assert.ThrowsAsync<ConversationProtocolException>(
            () => new OpenAiSseReader().ReadAsync(source, null, CancellationToken.None));

        Assert.Equal("STREAM_PROTOCOL_ERROR", error.Code);
    }

    [Fact]
    public async Task Cancellation_interrupts_a_stream_waiting_for_more_data()
    {
        await using var source = new BlockingReadStream();
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => new OpenAiSseReader().ReadAsync(source, null, cancellation.Token));
    }

    private sealed class InlineProgress<T>(Action<T> report) : IProgress<T>
    {
        public void Report(T value) => report(value);
    }

    private sealed class FragmentedReadStream(byte[] bytes, int fragmentSize) : Stream
    {
        private readonly MemoryStream _inner = new(bytes, writable: false);

        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => _inner.Length;
        public override long Position { get => _inner.Position; set => throw new NotSupportedException(); }
        public override void Flush() => throw new NotSupportedException();
        public override int Read(byte[] buffer, int offset, int count) =>
            _inner.Read(buffer, offset, Math.Min(count, fragmentSize));
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
            _inner.ReadAsync(buffer[..Math.Min(buffer.Length, fragmentSize)], cancellationToken);
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        protected override void Dispose(bool disposing)
        {
            if (disposing) _inner.Dispose();
            base.Dispose(disposing);
        }
        public override async ValueTask DisposeAsync()
        {
            await _inner.DisposeAsync();
            GC.SuppressFinalize(this);
        }
    }

    private sealed class BlockingReadStream : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override void Flush() => throw new NotSupportedException();
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return 0;
        }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
