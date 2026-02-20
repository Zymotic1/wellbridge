/**
 * Settings > Sharing page — RBAC Trusted Individual Access management.
 */

import RBACManager from "@/components/sharing/RBACManager";

export default function SharingSettingsPage() {
  return (
    <div className="p-6">
      <div className="max-w-2xl">
        <h1 className="text-xl font-bold text-slate-800 mb-1">Sharing & Access</h1>
        <p className="text-sm text-slate-500 mb-6">
          Control who can view or contribute to your health records.
          You can grant access to caregivers, family members, or other trusted individuals.
        </p>
        <RBACManager />
      </div>
    </div>
  );
}
