import { useContext } from "react";
import { identityApi } from "../../../providers/identity-api";
import { DreamProviderContext } from "../../providers";
import { imageDeletionStore } from "../../image-deletion-state";
import { DeleteImageButton } from "../DeleteImageButton";

export function DeleteIdentityBatchButton({ id, count, disabled }: { id: string; count: number; disabled?: boolean }) {
  const provider = useContext(DreamProviderContext);
  async function remove(batchId: string) {
    const receipt = await identityApi.deleteBatch(batchId);
    // One notification and storage write: sibling tabs never see half a batch.
    imageDeletionStore(provider ?? identityApi).confirmMany([receipt.deleted, ...receipt.deletedJobIds]);
  }
  return <DeleteImageButton id={id} batchCount={count} disabled={disabled} onDelete={remove} />;
}
