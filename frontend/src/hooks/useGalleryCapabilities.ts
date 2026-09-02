import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  GalleryCapabilities,
  GalleryWriteMode,
} from "../api/types";

// Fail closed while the authenticated capability response is loading or
// unavailable. The backend remains authoritative, so this only prevents stale
// UI controls from inviting an operation that the current mode would reject.
const READ_ONLY_CAPABILITIES: GalleryCapabilities = {
  physical_mutations: false,
  undo_drain: false,
  synology_curation: false,
  legacy_date_repair: false,
};

export function useGalleryCapabilities(): {
  capabilities: GalleryCapabilities;
  galleryWriteMode: GalleryWriteMode | null;
  isPending: boolean;
  isError: boolean;
} {
  const query = useQuery({
    queryKey: ["system-info"],
    queryFn: api.systemInfo,
    staleTime: 60_000,
    retry: 1,
  });
  return {
    capabilities: query.data?.capabilities ?? READ_ONLY_CAPABILITIES,
    galleryWriteMode: query.data?.gallery_write_mode ?? null,
    isPending: query.isPending,
    isError: query.isError,
  };
}
