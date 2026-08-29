using System.Buffers.Binary;

namespace MLLM.Workbench.Knowledge.Embeddings;

internal static class VectorCodec
{
    public static byte[] Encode(ReadOnlySpan<float> vector)
    {
        var bytes = new byte[vector.Length * sizeof(float)];
        for (var i = 0; i < vector.Length; i++)
            BinaryPrimitives.WriteSingleLittleEndian(bytes.AsSpan(i * sizeof(float), sizeof(float)), vector[i]);
        return bytes;
    }

    public static float[] Decode(ReadOnlySpan<byte> bytes, int dimension)
    {
        if (dimension < 1) throw new ArgumentOutOfRangeException(nameof(dimension));
        if (bytes.Length != dimension * sizeof(float))
            throw new InvalidDataException($"Vector byte length mismatch. expected={dimension * sizeof(float)} actual={bytes.Length}");

        var vector = new float[dimension];
        for (var i = 0; i < dimension; i++)
            vector[i] = BinaryPrimitives.ReadSingleLittleEndian(bytes.Slice(i * sizeof(float), sizeof(float)));
        return vector;
    }
}
