import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuthStore } from '../../store/auth'
import { cn } from '../../lib/utils'
import RootFolderAdmin from './RootFolderAdmin'
import VisibilityPrefs from './VisibilityPrefs'
import AccountSettings from './AccountSettings'

type Tab = 'folders' | 'account'

export default function SettingsPage() {
  const location = useLocation()
  const initialTab: Tab = (location.state as { tab?: Tab } | null)?.tab ?? 'folders'
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)
  const user = useAuthStore((s) => s.user)

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'folders', label: 'Root Folders' },
    { id: 'account', label: 'Account' },
  ]

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-bold text-neutral-100 mb-6">Settings</h1>

      {/* Tab bar */}
      <div className="flex border-b border-neutral-800 mb-6">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-5 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-neutral-400 hover:text-neutral-200 hover:border-neutral-600'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'folders' && (
        <div className="space-y-8">
          <section>
            <h2 className="text-base font-semibold text-neutral-200 mb-4">Sidebar Visibility</h2>
            <VisibilityPrefs />
          </section>

          {user?.role === 'admin' && (
            <section>
              <h2 className="text-base font-semibold text-neutral-200 mb-4">
                Manage Root Folders
              </h2>
              <RootFolderAdmin />
            </section>
          )}
        </div>
      )}

      {activeTab === 'account' && <AccountSettings />}
    </div>
  )
}
