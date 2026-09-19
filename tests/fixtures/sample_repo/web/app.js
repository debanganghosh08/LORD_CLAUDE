import { helper as h, helperConst } from './lib/helper';
import React from 'react';
const MAX_ITEMS = 10;

// render(items) draws the list
function render(items) {
  return h(items.slice(0, MAX_ITEMS));
}

export class Widget extends Base {
  draw() {
    return render([]);
  }
}

const onClick = (e) => render([e]);
app.get('/items', (req, res) => res.json(render([])));
export default render;
