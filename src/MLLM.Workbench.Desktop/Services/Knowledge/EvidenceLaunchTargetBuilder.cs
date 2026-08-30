using System.Globalization;
using System.IO;

namespace MLLM.Workbench.Desktop.Services.Knowledge;

public sealed record EvidenceLaunchTarget(
    string ResolvedPath,
    string ShellTarget,
    string? AppliedLocator,
    bool IsDeepLink);

public static class EvidenceLaunchTargetBuilder
{
    public static EvidenceLaunchTarget Build(string sourceUri, string? locator)
    {
        if (string.IsNullOrWhiteSpace(sourceUri))
            throw new ArgumentException("Evidence source is required.", nameof(sourceUri));

        var path = ResolveLocalPath(sourceUri);
        var normalizedLocator = string.IsNullOrWhiteSpace(locator) ? null : locator.Trim();

        if (string.Equals(Path.GetExtension(path), ".pdf", StringComparison.OrdinalIgnoreCase) &&
            TryParsePageLocator(normalizedLocator, out var page))
        {
            var fileUri = new Uri(path).AbsoluteUri;
            var applied = $"page={page}";
            return new EvidenceLaunchTarget(
                ResolvedPath: path,
                ShellTarget: $"{fileUri}#{applied}",
                AppliedLocator: applied,
                IsDeepLink: true);
        }

        return new EvidenceLaunchTarget(
            ResolvedPath: path,
            ShellTarget: path,
            AppliedLocator: null,
            IsDeepLink: false);
    }

    private static string ResolveLocalPath(string sourceUri)
    {
        if (Path.IsPathRooted(sourceUri))
            return Path.GetFullPath(sourceUri);

        if (Uri.TryCreate(sourceUri, UriKind.Absolute, out var uri))
        {
            if (!uri.IsFile)
                throw new NotSupportedException("Only local file evidence can be opened from the knowledge workbench.");
            return Path.GetFullPath(uri.LocalPath);
        }

        return Path.GetFullPath(sourceUri);
    }

    private static bool TryParsePageLocator(string? locator, out int page)
    {
        page = 0;
        if (string.IsNullOrWhiteSpace(locator) ||
            !locator.StartsWith("page=", StringComparison.OrdinalIgnoreCase))
            return false;

        return int.TryParse(
                   locator.AsSpan(5),
                   NumberStyles.None,
                   CultureInfo.InvariantCulture,
                   out page) &&
               page > 0;
    }
}
