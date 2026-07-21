/** 로컬 저장 유틸 — 지원 브라우저(Chrome/Edge 데스크톱)에선 File System Access
 * API(showSaveFilePicker)로 저장 위치·파일명을 직접 고르고, 응답 스트림을
 * 디스크에 바로 흘려 큰 동영상도 메모리에 안 쌓는다. 미지원 브라우저
 * (모바일 Chrome/Safari/Firefox)는 앵커 다운로드로 폴백 — 브라우저 다운로드
 * 관리자가 기본 다운로드 폴더에 저장한다(Android는 Chrome 설정의 "다운로드
 * 위치 확인"으로 매번 선택 가능). */

interface SaveFilePickerOptions {
  suggestedName?: string;
}

declare global {
  interface Window {
    // lib.dom엔 FileSystemFileHandle은 있지만 showSaveFilePicker는 아직 없다.
    showSaveFilePicker?: (
      options?: SaveFilePickerOptions,
    ) => Promise<FileSystemFileHandle>;
  }
}

export type SaveOutcome = "saved" | "cancelled" | "fallback";

/** 저장 위치 선택 다이얼로그를 띄울 수 있는 브라우저인지. */
export function canPickSaveLocation(): boolean {
  return typeof window.showSaveFilePicker === "function";
}

/** 앵커 다운로드 폴백 — 브라우저 다운로드 관리자에 위임. */
function saveViaAnchor(url: string, filename: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** 원본 파일을 로컬에 저장. 반드시 사용자 제스처(클릭 핸들러) 안에서 호출 —
 * showSaveFilePicker가 transient activation을 요구한다. */
export async function saveLocal(
  url: string,
  filename: string,
): Promise<SaveOutcome> {
  if (!canPickSaveLocation()) {
    saveViaAnchor(url, filename);
    return "fallback";
  }

  let handle: FileSystemFileHandle;
  try {
    handle = await window.showSaveFilePicker!({ suggestedName: filename });
  } catch (error) {
    // 사용자가 다이얼로그를 닫음 — 실패가 아니라 취소.
    if (error instanceof DOMException && error.name === "AbortError")
      return "cancelled";
    throw error;
  }

  const res = await fetch(url);
  if (!res.ok || !res.body) {
    throw new Error(`다운로드 실패 (HTTP ${res.status})`);
  }
  // pipeTo는 소스 에러 시 대상 스트림을 자동 abort — 부분 파일이 남지 않는다.
  const writable = await handle.createWritable();
  await res.body.pipeTo(writable);
  return "saved";
}
