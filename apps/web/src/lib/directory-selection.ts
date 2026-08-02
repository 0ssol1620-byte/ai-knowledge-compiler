import type { CollectionFileHandleRecord } from "@/lib/collection-storage";

export type DirectorySelection = {
  files: File[];
  handles: CollectionFileHandleRecord[];
  source: "file-system-access" | "data-transfer" | "file-list";
};

type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: (options?: {
    id?: string;
    mode?: "read" | "readwrite";
  }) => Promise<FileSystemDirectoryHandle>;
};

type LegacyFileEntry = {
  isFile: true;
  isDirectory: false;
  name: string;
  file: (success: (file: File) => void, failure?: (error: DOMException) => void) => void;
};

type LegacyDirectoryReader = {
  readEntries: (
    success: (entries: LegacyEntry[]) => void,
    failure?: (error: DOMException) => void,
  ) => void;
};

type LegacyDirectoryEntry = {
  isFile: false;
  isDirectory: true;
  name: string;
  createReader: () => LegacyDirectoryReader;
};

type LegacyEntry = LegacyFileEntry | LegacyDirectoryEntry;

export function supportsDirectoryPicker(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function"
  );
}

export async function selectDirectoryWithHandle(): Promise<
  DirectorySelection | undefined
> {
  const picker =
    typeof window === "undefined"
      ? undefined
      : (window as DirectoryPickerWindow).showDirectoryPicker;
  if (!picker) return undefined;
  try {
    const root = await picker.call(window, {
      id: "structara-collection-source",
      mode: "read",
    });
    const files: File[] = [];
    const handles: CollectionFileHandleRecord[] = [];
    await walkFileSystemDirectory(root, [root.name], files, handles);
    return { files, handles, source: "file-system-access" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return undefined;
    throw error;
  }
}

export async function filesFromDataTransfer(
  dataTransfer: DataTransfer,
): Promise<DirectorySelection> {
  const entries: LegacyEntry[] = [];
  for (const item of Array.from(dataTransfer.items)) {
    const withEntry = item as unknown as {
      webkitGetAsEntry?: () => LegacyEntry | null;
    };
    const entry = withEntry.webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  if (entries.length === 0) {
    return {
      files: Array.from(dataTransfer.files),
      handles: [],
      source: "file-list",
    };
  }
  const files: File[] = [];
  for (const entry of entries) {
    await walkLegacyEntry(entry, [], files);
  }
  return { files, handles: [], source: "data-transfer" };
}

async function walkFileSystemDirectory(
  directory: FileSystemDirectoryHandle,
  path: string[],
  files: File[],
  handles: CollectionFileHandleRecord[],
): Promise<void> {
  const iterable = directory as FileSystemDirectoryHandle & {
    entries: () => AsyncIterableIterator<[string, FileSystemHandle]>;
  };
  for await (const [name, handle] of iterable.entries()) {
    const nextPath = [...path, name];
    if (handle.kind === "directory") {
      await walkFileSystemDirectory(
        handle as FileSystemDirectoryHandle,
        nextPath,
        files,
        handles,
      );
      continue;
    }
    const fileHandle = handle as FileSystemFileHandle;
    const relativePath = nextPath.join("/");
    const file = await fileHandle.getFile();
    attachRelativePath(file, relativePath);
    files.push(file);
    handles.push({ relativePath, handle: fileHandle });
  }
}

async function walkLegacyEntry(
  entry: LegacyEntry,
  path: string[],
  files: File[],
): Promise<void> {
  const nextPath = [...path, entry.name];
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      entry.file(resolve, reject),
    );
    attachRelativePath(file, nextPath.join("/"));
    files.push(file);
    return;
  }
  const reader = entry.createReader();
  while (true) {
    const batch = await new Promise<LegacyEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (batch.length === 0) break;
    for (const child of batch) await walkLegacyEntry(child, nextPath, files);
  }
}

function attachRelativePath(file: File, relativePath: string): void {
  Object.defineProperty(file, "webkitRelativePath", {
    configurable: true,
    value: relativePath,
  });
}
