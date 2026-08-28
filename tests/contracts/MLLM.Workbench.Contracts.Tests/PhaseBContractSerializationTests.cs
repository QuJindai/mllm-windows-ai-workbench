using System.Text.Json;
using MLLM.Workbench.Contracts.Models;
using MLLM.Workbench.Contracts.Protocol;
using MLLM.Workbench.Contracts.Services;

namespace MLLM.Workbench.Contracts.Tests;

public sealed class PhaseBContractSerializationTests
{
    [Fact]
    public void Model_contract_round_trips_enum_names_and_unanchored_hash_state()
    {
        var input = new ModelDescriptor(
            "qwen35-4b-q4km",
            "local-fast",
            "Qwen3.5-4B Q4_K_M",
            ModelSourceKind.BuiltIn,
            @"C:\M-LLM\models\Qwen3.5-4B\Qwen3.5-4B-Q4_K_M.gguf",
            "Qwen3.5-4B-Q4_K_M.gguf",
            "gguf",
            "Q4_K_M",
            3_000_000_000,
            2_684_354_560,
            null,
            "0123456789abcdef",
            ModelIntegrityState.HashComputedUnanchored,
            true,
            null);

        var json = JsonSerializer.Serialize(input, WorkbenchJson.Options);
        var output = JsonSerializer.Deserialize<ModelDescriptor>(json, WorkbenchJson.Options)!;

        Assert.Equal(ModelIntegrityState.HashComputedUnanchored, output.IntegrityState);
        Assert.Null(output.ExpectedSha256);
        Assert.Contains("HashComputedUnanchored", json, StringComparison.Ordinal);
        Assert.Contains("\"expectedSha256\":null", json, StringComparison.Ordinal);
    }

    [Fact]
    public void Model_and_service_mutation_requests_preserve_operation_ids()
    {
        var model = new ModelActivateRequest("model-1", "model-operation-42");
        var service = new ServiceActionRequest("local-model-api", "service-operation-84");

        var modelJson = JsonSerializer.Serialize(model, WorkbenchJson.Options);
        var serviceJson = JsonSerializer.Serialize(service, WorkbenchJson.Options);

        Assert.Equal("model-operation-42", JsonSerializer.Deserialize<ModelActivateRequest>(modelJson, WorkbenchJson.Options)!.OperationId);
        Assert.Equal("service-operation-84", JsonSerializer.Deserialize<ServiceActionRequest>(serviceJson, WorkbenchJson.Options)!.OperationId);
    }

    [Fact]
    public void Service_and_capability_contracts_use_stable_string_states()
    {
        var service = new ServiceDescriptor(
            "web-workbench",
            "Web Workbench",
            ManagedServiceState.Blocked,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            "runtime missing",
            null,
            null,
            false,
            false,
            false,
            "SERVICE_RUNTIME_MISSING");
        var capabilities = new BackendCapabilitiesSnapshot("phase-b", ["models.snapshot", "services.snapshot"]);

        var json = JsonSerializer.Serialize(service, WorkbenchJson.Options);
        var roundTrip = JsonSerializer.Deserialize<ServiceDescriptor>(json, WorkbenchJson.Options)!;

        Assert.Equal(ManagedServiceState.Blocked, roundTrip.State);
        Assert.Contains("Blocked", json, StringComparison.Ordinal);
        Assert.Equal(["models.snapshot", "services.snapshot"], capabilities.Methods);
    }
}
