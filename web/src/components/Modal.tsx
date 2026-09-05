import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

export function Modal({
  title,
  children,
  close,
}: {
  title: string
  children: ReactNode
  close: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    dialog.showModal()
    return () => dialog.close()
  }, [])
  return (
    <dialog ref={ref} onCancel={close} aria-labelledby="modal-title">
      <header>
        <h2 id="modal-title">{title}</h2>
        <button className="icon-button" onClick={close} aria-label="Close">
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  )
}
