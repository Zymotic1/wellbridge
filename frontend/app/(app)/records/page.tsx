/**
 * Records page — displays the patient's medical records and the
 * Scan-to-Calendar upload component.
 */

"use client";

import { useState, useEffect } from "react";
import { FileText, Loader2, Calendar } from "lucide-react";
import type { PatientRecord } from "@/lib/types";
import ScanUpload from "@/components/records/ScanUpload";

const RECORD_TYPE_LABELS: Record<string, string> = {
  clinical_note: "Clinical Note",
  lab_result: "Lab Result",
  discharge_summary: "Discharge Summary",
  prescription: "Prescription",
  imaging_report: "Imaging Report",
};

export default function RecordsPage() {
  const [records, setRecords] = useState<PatientRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRecord, setSelectedRecord] = useState<PatientRecord | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/backend/records/");
        if (res.ok) {
          const data = await res.json();
          setRecords(data.records ?? []);
        }
      } catch {
        // Ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return (
    <div className="flex h-screen">
      {/* Records list */}
      <div className="w-80 border-r border-slate-200 bg-white flex flex-col">
        <div className="p-5 border-b border-slate-100">
          <h1 className="text-lg font-semibold text-slate-800">My Records</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {records.length} record{records.length !== 1 ? "s" : ""}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {loading ? (
            <div className="flex items-center gap-2 text-slate-400 text-sm p-5">
              <Loader2 size={14} className="animate-spin" />
              Loading records...
            </div>
          ) : records.length === 0 ? (
            <div className="p-5 text-sm text-slate-400">
              No records yet. Upload a document below to get started.
            </div>
          ) : (
            records.map((record) => (
              <button
                key={record.id}
                onClick={() => setSelectedRecord(record)}
                className={`w-full text-left p-4 hover:bg-slate-50 transition-colors
                             ${selectedRecord?.id === record.id ? "bg-brand-50" : ""}`}
              >
                <div className="flex items-start gap-3">
                  <FileText
                    size={18}
                    className={
                      selectedRecord?.id === record.id
                        ? "text-brand-600 flex-shrink-0 mt-0.5"
                        : "text-slate-400 flex-shrink-0 mt-0.5"
                    }
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-700 truncate">
                      {RECORD_TYPE_LABELS[record.record_type] ?? record.record_type}
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {record.provider_name ?? "Unknown provider"}
                    </p>
                    <p className="text-xs text-slate-400">
                      {new Date(record.note_date).toLocaleDateString("en-US", {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </p>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right panel: record detail or scan upload */}
      <div className="flex-1 overflow-auto p-6 bg-slate-50">
        {selectedRecord ? (
          <div className="max-w-3xl mx-auto">
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-6 py-5 border-b border-slate-100">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold text-slate-800">
                      {RECORD_TYPE_LABELS[selectedRecord.record_type]}
                    </h2>
                    <p className="text-sm text-slate-500 mt-0.5">
                      {selectedRecord.provider_name} ·{" "}
                      {new Date(selectedRecord.note_date).toLocaleDateString("en-US", {
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                      })}
                    </p>
                  </div>
                  <button
                    onClick={() => setSelectedRecord(null)}
                    className="text-sm text-slate-400 hover:text-slate-600"
                  >
                    Close
                  </button>
                </div>
              </div>
              <div className="p-6">
                <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">
                  {selectedRecord.content}
                </pre>
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-xl mx-auto space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-slate-800 mb-1">
                Upload a Document
              </h2>
              <p className="text-sm text-slate-500">
                Upload discharge papers or referral letters. I'll automatically
                detect follow-up appointment instructions.
              </p>
            </div>
            <ScanUpload />
          </div>
        )}
      </div>
    </div>
  );
}
