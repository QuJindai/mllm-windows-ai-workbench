using System.Windows;

namespace MLLM.Workbench.Desktop.Services;

public interface IClipboardService
{
    void SetText(string text);
}

public sealed class WpfClipboardService : IClipboardService
{
    public void SetText(string text)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(text);
        Clipboard.SetText(text);
    }
}
