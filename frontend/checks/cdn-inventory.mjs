import assert from 'node:assert/strict';

// Keep the existing host redirect, private CSR and genuine 404 contract unchanged.
export function prepareStaticRouteStack(template, routes) {
  assert.ok(Array.isArray(routes) && routes.length > 0 && routes.length <= 64);
  const paths = routes.map(path => {
    assert.ok(typeof path === 'string' && path.length <= 128
      && (path === '' || path === 'tr/' || /^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(path))
      && !/^(?:tr\/)?(?:account|app)(?:\/|$)/.test(path));
    return path.replace(/\/$/, '');
  });
  assert.equal(new Set(paths).size, paths.length);
  const stack = structuredClone(template);
  const code = stack.Resources.StaticRouteFunction.Properties.FunctionCode;
  const source = code['Fn::Sub'];
  const start = source.indexOf("  if (uri === '/')");
  const end = source.indexOf('  if (/^');
  assert.ok(start >= 0 && end > start, 'Static template route boundaries changed');
  code['Fn::Sub'] = source.slice(0, start)
    + `  var paths = ${JSON.stringify(paths)};\n`
    + "  for (var i = 0; i < paths.length; i++) {\n"
    + "    var path = paths[i];\n"
    + "    if (uri === '/' + path || (path && uri === '/' + path + '/')) {\n"
    + "      request.uri = path ? '/' + path + '/index.html' : '/index.html'; return request;\n"
    + "    }\n  }\n"
    + source.slice(end);
  return stack;
}
