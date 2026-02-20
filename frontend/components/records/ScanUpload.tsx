"use client";

/**
 * ScanUpload — Drag-and-drop document upload for Scan-to-Calendar.
 *
 * Uploads a medical document to /api/upload (which proxies to /ocr/upload on FastAPI).
 * On success, passes the extracted appointments to CalendarConfirmDialog.
 */

import { useState, useRef } from "react";
import { Upload, FileText, Loader2 } from "lucide-react";
import type { ExtractedAppointment } from "@/lib/types";
import CalendarConfirmDialog from "./CalendarConfirmDialog";

export default function ScanUpload() {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extractedAppointments, setExtractedAppointments] = useState<
    ExtractedAppointment[] | null
  >(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setIsUploading(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail ?? "Upload failed");
      }

      const data = await res.json();
      setExtractedAppointments(data.extracted_appointments ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed. Please try again.");
    } finally {
      setIsUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  if (extractedAppointments) {
    return (
      <CalendarConfirmDialog
        appointments={extractedAppointments}
        onDismiss={() => setExtractedAppointments(null)}
      />
    );
  }

  return (
    <div className="rounded-2xl border-2 border-dashed border-slate-300 p-8 text-center
                    hover:border-brand-400 transition-colors bg-white">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={`${isDragging ? "opacity-60" : ""} transition-opacity`}
      >
        <div className="flex flex-col items-center gap-4">
          <div className="w-14 h-14 bg-brand-50 rounded-2xl flex items-center justify-center">
            {isUploading ? (
              <Loader2 size={28} className="text-brand-600 animate-spin" />
            ) : (
              <Upload size={28} className="text-brand-600" />
            )}
          </div>

          <div>
            <p className="font-semibold text-slate-700">
              {isUploading ? "Processing document..." : "Upload a medical document"}
            </p>
            <p className="text-sm text-slate-400 mt-1">
              Discharge papers, referral letters, clinical notes
            </p>
            <p className="text-xs text-slate-400 mt-0.5">PDF, JPEG, PNG up to 20 MB</p>
          </div>

          {!isUploading && (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-5 py-2.5 bg-brand-600 text-white rounded-xl text-sm font-medium
                         hover:bg-brand-700 transition-colors"
            >
              Choose file
            </button>
          )}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.tiff"
          onChange={onFileChange}
          className="hidden"
        />
      </div>

      {error && (
        <p className="mt-4 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-2">
          {error}
        </p>
      )}

      <div className="mt-4 flex items-center gap-2 justify-center text-xs text-slate-400">
        <FileText size={14} />
        <span>I'll look for follow-up appointment instructions automatically</span>
      </div>
    </div>
  );
}
