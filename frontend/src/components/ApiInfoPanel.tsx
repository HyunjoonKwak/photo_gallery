import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

// Step-3 verification surface: after login, show what SYNO.API.Info actually
// reports for each core API (real path/version) against the live NAS.
export function ApiInfoPanel() {
  const query = useQuery({
    queryKey: ["system-info"],
    queryFn: api.systemInfo,
  });

  if (query.isPending) {
    return <p className="text-slate-500">NAS API 정보를 조회 중...</p>;
  }
  if (query.isError) {
    return (
      <p className="text-red-600">
        API 정보 조회 실패: {(query.error as Error).message}
      </p>
    );
  }

  const { dsm_webapi_base, endpoints } = query.data;
  const availableCount = endpoints.filter((e) => e.available).length;

  return (
    <div className="space-y-3">
      <div className="text-sm text-slate-500">
        대상: <code className="text-slate-700">{dsm_webapi_base}</code> · 사용 가능{" "}
        {availableCount}/{endpoints.length}
      </div>
      <div className="overflow-hidden rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">API</th>
              <th className="text-left px-3 py-2">path</th>
              <th className="text-left px-3 py-2">version</th>
              <th className="text-left px-3 py-2">상태</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.map((e) => (
              <tr key={e.api} className="border-t border-slate-100">
                <td className="px-3 py-2 font-mono text-xs text-slate-800">
                  {e.api}
                </td>
                <td className="px-3 py-2 text-slate-600">{e.path || "—"}</td>
                <td className="px-3 py-2 text-slate-600">
                  {e.available ? `${e.min_version}–${e.max_version}` : "—"}
                </td>
                <td className="px-3 py-2">
                  {e.available ? (
                    <span className="text-green-600">사용 가능</span>
                  ) : (
                    <span className="text-amber-600">없음</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
