using System.Windows.Input;

namespace MLLM.Workbench.Desktop.Shell;

public sealed record NavigationItem(string Route, string Title, ICommand Command);
