import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ShoppingProjectSelect } from '../src/ShoppingProjectSelect'

describe('Shopping project selection', () => {
  it('renders an owned project label with its current revision', () => {
    const markup = renderToStaticMarkup(
      createElement(ShoppingProjectSelect, {
        choices: [
          {
            project_id: '00000000-0000-0000-0000-000000000001',
            label: 'Carry-on bag',
            revision: 4,
          },
        ],
        selectedId: '',
        onSelect: () => undefined,
      }),
    )

    expect(markup).toContain('Carry-on bag (revision 4)')
    expect(markup).toContain('Select an active Shopping project')
    expect(markup).not.toContain('Current project revision')
    expect(markup).not.toContain('Shopping project ID')
  })
})
