#include <cuda_runtime.h>
#include <cstdio>

__global__ void add_values(float* output) {
    const int i = threadIdx.x;
    output[i] = static_cast<float>(i + 7);
}
int main() {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count < 1) return 1;
    cudaDeviceProp device{};
    if (cudaGetDeviceProperties(&device, 0) != cudaSuccess) return 2;
    float* output = nullptr;
    if (cudaMalloc(&output, 256 * sizeof(float)) != cudaSuccess) return 3;
    add_values<<<1, 256>>>(output);
    if (cudaGetLastError() != cudaSuccess || cudaDeviceSynchronize() != cudaSuccess) return 4;
    float values[256]{};
    if (cudaMemcpy(values, output, sizeof(values), cudaMemcpyDeviceToHost) != cudaSuccess) return 5;
    cudaFree(output);
    for (int i = 0; i < 256; ++i) if (values[i] != static_cast<float>(i + 7)) return 6;
    int runtime = 0, driver = 0;
    cudaRuntimeGetVersion(&runtime);
    cudaDriverGetVersion(&driver);
    std::printf("CUDA_KERNEL_PASS device=%s capability=%d.%d runtime=%d driver=%d vram=%llu\n",
                device.name, device.major, device.minor, runtime, driver,
                static_cast<unsigned long long>(device.totalGlobalMem));
    return cudaDeviceReset() == cudaSuccess ? 0 : 7;
}
