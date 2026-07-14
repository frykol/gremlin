const express = require('express');
const path = require('path');

function createApp() {
  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  return app;
}

module.exports = { createApp };

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const app = createApp();
  app.listen(PORT, () => {
    console.log(`Control site listening on :${PORT}`);
  });
}
