using System.Threading;
using System.Windows;
using MLLM.Workbench.Desktop.Pages.Knowledge;

namespace MLLM.Workbench.Desktop.Tests;

public sealed class KnowledgePageRuntimeLoadTests
{
    [Fact]
    public void Knowledge_page_loads_with_real_application_resources_on_sta_thread()
    {
        Exception? failure = null;
        using var completed = new ManualResetEventSlim(false);

        var thread = new Thread(() =>
        {
            App? app = null;
            try
            {
                app = new App();
                app.InitializeComponent();

                var page = new KnowledgePage();
                page.Measure(new Size(1200, 4000));
                page.Arrange(new Rect(0, 0, 1200, 4000));
                page.UpdateLayout();
            }
            catch (Exception ex)
            {
                failure = ex;
            }
            finally
            {
                try { app?.Shutdown(); } catch { }
                completed.Set();
            }
        })
        {
            IsBackground = true,
            Name = "KnowledgePageRuntimeLoadTest"
        };

        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();

        Assert.True(completed.Wait(TimeSpan.FromSeconds(20)), "Knowledge page runtime load did not complete within 20 seconds.");
        thread.Join(TimeSpan.FromSeconds(2));
        Assert.Null(failure);
    }
}
