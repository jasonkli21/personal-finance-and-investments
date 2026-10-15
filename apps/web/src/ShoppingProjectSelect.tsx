type Choice = { project_id: string; label: string; revision: number }

export function ShoppingProjectSelect({
  choices,
  selectedId,
  onSelect,
}: {
  choices: Choice[]
  selectedId: string
  onSelect: (projectId: string) => void
}) {
  return (
    <label>
      Shopping project{' '}
      <select value={selectedId} onChange={(event) => onSelect(event.target.value)}>
        <option value="">Select an active Shopping project</option>
        {choices.map((item) => (
          <option key={item.project_id} value={item.project_id}>
            {item.label} (revision {item.revision})
          </option>
        ))}
      </select>
    </label>
  )
}
