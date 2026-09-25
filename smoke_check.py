import io
import pythonizeyaml as py

print('import from:', py.__file__)
print('version:', py.__version__)

src = open('tests/fixtures/rich.yaml', encoding='utf-8').read()
d = py.load(src)
d['server']['port'] = 9090
out = py.dump(d)
print('edit-isolated:', out == src.replace('8080', '9090'))
print('no drift:', py.dump(py.load(src)) == src)
print('stream returns None:', py.dump({'a': 1}, stream=io.StringIO()) is None)

try:
    py.load('items: [1, 2, 3\n')
except py.YAMLError as e:
    print('err:', type(e).__name__, '| module:', type(e).__module__,
          '| has problem_mark:', getattr(e, 'problem_mark', None) is not None)

try:
    py.safe_load('!!python/object/apply:os.system ["echo hi"]\n')
except py.ConstructorError:
    print('safe rejects object tag: True')

e4 = py.YAML(py.IndentConfig(mapping=4, sequence=4, offset=2))
print('fresh uses config:', repr(e4.dump({'a': {'b': 1}, 'items': [1]})))

four = open('tests/fixtures/simple_4space.yaml', encoding='utf-8').read()
hint = py.YAML().load(four)
print('hint beats engine config:',
      py.YAML(py.IndentConfig(mapping=2)).dump(hint) == four)

try:
    py.dump({'a': 1}, bogus=1)
except TypeError as e:
    print('bad kwarg:', e)

print('dump kwargs ignored:', py.dump({'a': 1}, sort_keys=True) == py.dump({'a': 1}))
print('load refuses multi-doc:', end=' ')
try:
    py.load('---\na: 1\n---\nb: 2\n')
except py.ComposerError:
    print(True)
