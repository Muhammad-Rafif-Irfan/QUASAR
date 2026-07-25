import { useState, type FormEvent } from 'react'
import { X } from 'lucide-react'

export type NewOrderDraft = {
  address: string
  weight: string
  startTime: string
  endTime: string
  priority: string
  assignment: string
}

type ChangeAddressModalProps = {
  onClose: () => void
  onUpdate: (address: string) => void
}

type AddNewOrderModalProps = {
  onClose: () => void
  onAdd: (draft: NewOrderDraft, shouldReRoute: boolean) => void
}

// Supporting state from the wireframe: it updates one affected delivery node.
export function ChangeAddressModal({ onClose, onUpdate }: ChangeAddressModalProps) {
  const [newAddress, setNewAddress] = useState('')

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onUpdate(newAddress)
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="supporting-modal" aria-modal="true" aria-labelledby="change-address-title" onSubmit={handleSubmit}>
        <header className="supporting-modal__header"><div><p className="section-label">Change address</p><h2 id="change-address-title">Update delivery location</h2></div><button type="button" className="modal-close" onClick={onClose} aria-label="Close change address"><X size={16} /></button></header>
        <p className="supporting-modal__copy">Update one delivery node and prepare the affected route for recalculation.</p>
        <div className="supporting-fields">
          <label>Current address<input value="N4 / current location" readOnly /></label>
          <label>New address<input value={newAddress} onChange={(event) => setNewAddress(event.target.value)} placeholder="Enter address" required /></label>
          <label>Reason<input defaultValue="Address changed" /></label>
          <label>Affected node<input value="N4" readOnly /></label>
          <label>Time window<select defaultValue="10:00–11:00"><option>10:00–11:00</option><option>09:00–10:00</option></select></label>
        </div>
        <footer className="supporting-modal__actions"><button type="submit" className="route-action">Update Address</button><button type="button" className="settings-button" onClick={onClose}>Cancel</button></footer>
      </form>
    </div>
  )
}

// Supporting state from the wireframe: it inserts an incoming delivery into the mock event queue.
export function AddNewOrderModal({ onClose, onAdd }: AddNewOrderModalProps) {
  const [draft, setDraft] = useState<NewOrderDraft>({ address: '', weight: '', startTime: '10:00', endTime: '11:00', priority: 'Normal', assignment: 'Auto-select vehicle' })

  const updateDraft = (field: keyof NewOrderDraft, value: string) => setDraft((currentDraft) => ({ ...currentDraft, [field]: value }))
  const submitOrder = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    onAdd(draft, submitter?.value === 'reroute')
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="supporting-modal" aria-modal="true" aria-labelledby="add-order-title" onSubmit={submitOrder}>
        <header className="supporting-modal__header"><div><p className="section-label">Add new order</p><h2 id="add-order-title">Create delivery request</h2></div><button type="button" className="modal-close" onClick={onClose} aria-label="Close add new order"><X size={16} /></button></header>
        <p className="supporting-modal__copy">Add the delivery to the event queue, then continue monitoring or re-route the affected nodes.</p>
        <div className="supporting-fields">
          <label>Customer address<input value={draft.address} onChange={(event) => updateDraft('address', event.target.value)} placeholder="Enter address" required /></label>
          <label>Package weight<input type="number" min="0" value={draft.weight} onChange={(event) => updateDraft('weight', event.target.value)} placeholder="kg" required /></label>
          <label>Time-window start<input type="time" value={draft.startTime} onChange={(event) => updateDraft('startTime', event.target.value)} required /></label>
          <label>Time-window end<input type="time" value={draft.endTime} onChange={(event) => updateDraft('endTime', event.target.value)} required /></label>
          <label>Priority<select value={draft.priority} onChange={(event) => updateDraft('priority', event.target.value)}><option>Normal</option><option>Urgent</option></select></label>
          <label>Assignment<select value={draft.assignment} onChange={(event) => updateDraft('assignment', event.target.value)}><option>Auto-select vehicle</option><option>Truck 1</option><option>Truck 2</option></select></label>
        </div>
        <footer className="supporting-modal__actions"><button type="submit" className="route-action" value="add">Add Order</button><button type="submit" className="settings-button" value="reroute">Add + Re-Route</button><button type="button" className="settings-button" onClick={onClose}>Cancel</button></footer>
      </form>
    </div>
  )
}
