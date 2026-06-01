import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { listUsers, createUser, updateUser, deleteUser } from '../../api/index'
import { patchMyPreferences } from '../../api/auth'
import type { UserResponse } from '../../types/api'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Modal } from '../ui/Modal'
import { Badge } from '../ui/Badge'
import { Spinner } from '../ui/Spinner'
import { Toggle } from '../ui/Toggle'
import { formatDate } from '../../lib/utils'
import client from '../../api/client'

// Change password form
function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const mutation = useMutation({
    mutationFn: async () => {
      await client.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
    },
    onSuccess: () => {
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirm('')
      setError(null)
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to change password'
      setError(typeof msg === 'string' ? msg : 'Failed to change password')
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword !== confirm) {
      setError('New passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    setError(null)
    setSuccess(false)
    mutation.mutate()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-sm">
      <h3 className="text-sm font-semibold text-neutral-200">Change Password</h3>

      <Input
        id="current-password"
        label="Current password"
        type="password"
        required
        value={currentPassword}
        onChange={(e) => setCurrentPassword(e.target.value)}
        autoComplete="current-password"
      />
      <Input
        id="new-password"
        label="New password"
        type="password"
        required
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        autoComplete="new-password"
      />
      <Input
        id="confirm-password"
        label="Confirm new password"
        type="password"
        required
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        autoComplete="new-password"
      />

      {error && <p className="text-sm text-red-400">{error}</p>}
      {success && <p className="text-sm text-green-400">Password changed successfully.</p>}

      <Button type="submit" loading={mutation.isPending}>
        Update Password
      </Button>
    </form>
  )
}

// Create user modal
function CreateUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<'viewer' | 'admin'>('viewer')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      createUser({ email, password, full_name: fullName || undefined, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      handleClose()
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to create user'
      setError(typeof msg === 'string' ? msg : 'Failed to create user')
    },
  })

  function handleClose() {
    setEmail('')
    setPassword('')
    setFullName('')
    setRole('viewer')
    setError(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Create User">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
        className="space-y-4"
      >
        <Input
          id="new-user-email"
          label="Email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          id="new-user-fullname"
          label="Full name (optional)"
          type="text"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        <Input
          id="new-user-password"
          label="Password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="new-user-role" className="text-sm text-neutral-300 font-medium">
            Role
          </label>
          <select
            id="new-user-role"
            value={role}
            onChange={(e) => setRole(e.target.value as 'viewer' | 'admin')}
            className="rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex gap-3 justify-end pt-2">
          <Button variant="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            Create User
          </Button>
        </div>
      </form>
    </Modal>
  )
}

// Admin user management table
function UserManagement() {
  const queryClient = useQueryClient()
  const currentUser = useAuthStore((s) => s.user)
  const [showCreateModal, setShowCreateModal] = useState(false)

  const { data: users, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: listUsers,
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateUser>[1] }) =>
      updateUser(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  if (isLoading) {
    return <Spinner />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-neutral-200">Users</h3>
        <Button size="sm" onClick={() => setShowCreateModal(true)}>
          + Add User
        </Button>
      </div>

      <div className="rounded-lg border border-neutral-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 bg-neutral-800/50">
              <th className="text-left px-4 py-2.5 text-xs text-neutral-400 font-medium">User</th>
              <th className="text-left px-4 py-2.5 text-xs text-neutral-400 font-medium">Role</th>
              <th className="text-left px-4 py-2.5 text-xs text-neutral-400 font-medium hidden md:table-cell">
                Last login
              </th>
              <th className="text-left px-4 py-2.5 text-xs text-neutral-400 font-medium">
                Active
              </th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {(users ?? []).map((u: UserResponse) => (
              <tr key={u.id} className="hover:bg-neutral-800/30">
                <td className="px-4 py-3">
                  <div>
                    <p className="text-neutral-200 font-medium">{u.full_name ?? u.email}</p>
                    {u.full_name && (
                      <p className="text-xs text-neutral-500">{u.email}</p>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge variant={u.role === 'admin' ? 'blue' : 'neutral'}>{u.role}</Badge>
                </td>
                <td className="px-4 py-3 text-neutral-500 text-xs hidden md:table-cell">
                  {formatDate(u.last_login_at)}
                </td>
                <td className="px-4 py-3">
                  <Toggle
                    checked={u.is_active}
                    onChange={(active) =>
                      updateMutation.mutate({ id: u.id, data: { is_active: active } })
                    }
                    disabled={u.id === currentUser?.id || updateMutation.isPending}
                  />
                </td>
                <td className="px-4 py-3 text-right">
                  {u.id !== currentUser?.id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-red-400 hover:text-red-300"
                      onClick={() => {
                        if (confirm(`Delete user ${u.email}?`)) {
                          deleteMutation.mutate(u.id)
                        }
                      }}
                      loading={deleteMutation.isPending}
                    >
                      Delete
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateUserModal open={showCreateModal} onClose={() => setShowCreateModal(false)} />
    </div>
  )
}

function FaceThresholdSetting() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const [value, setValue] = useState(String(user?.face_cluster_min_size ?? 20))

  const mutation = useMutation({
    mutationFn: (n: number) => patchMyPreferences({ face_cluster_min_size: n }),
    onSuccess: (updatedUser) => setUser(updatedUser),
  })

  function handleBlur() {
    const n = parseInt(value, 10)
    if (!isNaN(n) && n >= 1 && n !== user?.face_cluster_min_size) {
      mutation.mutate(n)
    }
  }

  return (
    <div className="max-w-sm space-y-3">
      <h3 className="text-sm font-semibold text-neutral-200">People</h3>
      <div className="rounded-lg border border-neutral-700 bg-neutral-800/30 p-4 space-y-2">
        <label htmlFor="face-threshold" className="text-sm text-neutral-300 font-medium">
          Minimum appearances to show a person
        </label>
        <p className="text-xs text-neutral-500">
          Persons with fewer detected face appearances than this threshold are hidden from the People page.
        </p>
        <input
          id="face-threshold"
          type="number"
          min={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={handleBlur}
          className="w-24 rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {mutation.isPending && <p className="text-xs text-neutral-500">Saving…</p>}
      </div>
    </div>
  )
}

function DiskDeletionToggle() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  const mutation = useMutation({
    mutationFn: (val: boolean) => patchMyPreferences({ allow_disk_deletion: val }),
    onSuccess: (updatedUser) => setUser(updatedUser),
  })

  return (
    <div className="max-w-sm space-y-3">
      <h3 className="text-sm font-semibold text-neutral-200">Disk Deletion</h3>
      <div className={`rounded-lg border p-4 space-y-3 ${user?.allow_disk_deletion ? 'border-red-800/60 bg-red-950/30' : 'border-neutral-700 bg-neutral-800/30'}`}>
        <div className="flex items-start gap-3">
          <AlertTriangle size={16} className={`shrink-0 mt-0.5 ${user?.allow_disk_deletion ? 'text-red-400' : 'text-neutral-500'}`} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-neutral-200">Allow Delete</p>
            <p className="text-xs text-neutral-400 mt-0.5">
              When enabled, files can be permanently deleted from disk. This action is irreversible.
            </p>
          </div>
          <Toggle
            checked={user?.allow_disk_deletion ?? false}
            onChange={(val) => mutation.mutate(val)}
            disabled={mutation.isPending}
          />
        </div>
        {user?.allow_disk_deletion && (
          <p className="text-xs text-red-400 pl-7">
            Disk deletion is active. A warning banner will appear in the sidebar.
          </p>
        )}
      </div>
    </div>
  )
}

export default function AccountSettings() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="space-y-10">
      <FaceThresholdSetting />
      <DiskDeletionToggle />
      <ChangePasswordForm />

      {user?.role === 'admin' && (
        <div>
          <UserManagement />
        </div>
      )}
    </div>
  )
}
