"""simple structural text templating """

# in public domain, with no warranty,
# by Masaaki Shibata <mshibata@emptypage.jp>


import re
import sys
from __builtin__ import compile as _compile


__version__ = '$Rev: 2199 $'


tagset = [('block', '{%', '%}'),
          ('variable', '{{', '}}'),
          ('comment', '{#', '#}'),]
rx_stags = re.compile('|'.join(re.escape(x[1]) for x in tagset))


class TextTemplateError(Exception):
    pass


class TemplateSyntaxError(Exception):
    pass


class EncodingDetected(Exception):
    # (internal use)
    pass


class NonEscapeValue(object):
    def __init__(self, value):
        self.value = value


class Node(object):
    # (abstruct)
    pass


class Variable(Node):

    def __init__(self, expr):
        self.codeobj = _compile(expr, '<string>', 'eval')

    def evaluate(self, namespace):

        obj = eval(self.codeobj, namespace)
        escape = namespace.get('__escape__')
        if escape:
            if isinstance(obj, NonEscapeValue):
                ret = unicode(obj.value)
            else:
                ret = escape(unicode(obj))
        else:
            ret = unicode(obj)
        return ret


class Block(Node):

    def __init__(self):
        self.childnodes = []

    def appendchild(self, childnode):
        self.childnodes.append(childnode)

    def evaluate(self, namespace):
        return ''.join([x.evaluate(namespace) for x in self.childnodes])


class IfBlock(Block):

    def __init__(self, expr):

        Block.__init__(self)
        self.codeobj_list = [_compile(expr.strip(), '<string>', 'eval')]
        self.ifnodes_list = [self.childnodes]
        self.elsenodes = []

    def elif_(self, expr):

        if self.childnodes is self.elsenodes:
            raise TextTemplateError('else_() has already been called')

        self.codeobj_list.append(_compile(expr.strip(), '<string>', 'eval'))
        self.childnodes = []
        self.ifnodes_list.append(self.childnodes)

    def else_(self):

        if self.childnodes is self.elsenodes:
            raise TextTemplateError('else_() has already been called')

        self.childnodes = self.elsenodes

    def evaluate(self, namespace):

        for codeobj, childnodes in zip(self.codeobj_list, self.ifnodes_list):
            if eval(codeobj, namespace):
                self.childnodes = childnodes
                break
        else:
            self.childnodes = self.elsenodes

        return Block.evaluate(self, namespace)


class ForBlock(Block):

    def __init__(self, expr):

        Block.__init__(self)
        self.codeobj = _compile('(locals() for %s)' % expr, '<string>', 'eval')

    def evaluate(self, namespace):

        results = []
        for localnamespace in eval(self.codeobj, namespace):
            namespace.update(localnamespace)
            results.append(Block.evaluate(self, namespace))

        return ''.join(results)


class ExecBlock(Block):

    def execute(self, namespace):
        exec(Block.evaluate(self, namespace), namespace)

    def evaluate(self, namespace):
        return ''


class EncodingBlock(Block):
    pass


class Text(Node):

    rx_escape = re.compile(r'^[ \t]*\\(?!\n)|\\\n', re.M)

    def __init__(self, data):
        self.value = self.rx_escape.sub('', data)

    def evaluate(self, namespace):
        return self.value


class Template(Block):

    """simple structural text template class """

    encoding = None

    def __init__(self, code=''):

        Block.__init__(self)
        self.namespace = {}

        parse(code, TemplateHandler(self))

        if '__escape__' in self.namespace:
            self.namespace['__nonescape__'] = NonEscapeValue

    def evaluate(self, namespace=None, **kwds):

        """apply values in namespace to the template and return result """

        nsglobal = self.namespace.copy()
        if namespace:
            nsglobal.update(namespace)
        if kwds:
            nsglobal.update(kwds)
        return Block.evaluate(self, nsglobal)


class TemplateHandler(object):

    def __init__(self, root):
        self.root = root
        self.nodestack = [self.root]

    def get_result(self):

        if len(self.nodestack) != 1:
            raise TemplateSyntaxError('invalid syntax')

        return self.root

    def handle_block(self, expr):

        tokens = expr.split(None, 1)
        if not tokens:
            raise TemplateSyntaxError('invalid syntax')
        tagname = tokens.pop(0)
        params = ''.join(tokens)

        if tagname == 'end':
            node = self.nodestack.pop()
            if isinstance(node, ExecBlock):
                node.execute(self.root.namespace)
            if isinstance(node, EncodingBlock) and not self.root.encoding:
                self.root.encoding = encoding = node.evaluate({}).strip()
                raise EncodingDetected(encoding)
        elif tagname == 'if':
            node = IfBlock(params)
            self.nodestack[-1].appendchild(node)
            self.nodestack.append(node)
        elif tagname == 'elif':
            try:
                elif_ = getattr(self.nodestack[-1], 'elif_')
            except AttributeError:
                raise TemplateSyntaxError('invalid syntax')
            elif_(params)
        elif tagname == 'else':
            try:
                else_ = getattr(self.nodestack[-1], 'else_')
            except AttributeError:
                raise TemplateSyntaxError('invalid syntax')
            else_()
        elif tagname == 'for':
            node = ForBlock(params)
            self.nodestack[-1].appendchild(node)
            self.nodestack.append(node)
        elif tagname == 'exec':
            node = ExecBlock()
            self.nodestack[-1].appendchild(node)
            self.nodestack.append(node)
        elif tagname == 'encoding':
            node = EncodingBlock()
            self.nodestack[-1].appendchild(node)
            self.nodestack.append(node)
        else:
            raise TemplateSyntaxError('invalid tag name %r' % tagname)

    def handle_variable(self, expr):
        self.nodestack[-1].appendchild(Variable(expr))

    def handle_comment(self, expr):
        pass

    def handle_text(self, expr):
        self.nodestack[-1].appendchild(Text(expr))


def compile_until(terminators, source, filename, mode, flags=0, dont_inherit=0):

    """Do built-in `compile()` until one of the tokens in
    `terminators` found in `source`.

    Return `(codeobj, offset)` tuple.

    The argument `terminators` is a list of string tokens specifies
    the end of the source code.

    >>> src = 'a=3}}'
    >>> codeobj, offset = compile_until(['}}'], src, '<string>', 'exec')
    >>> src[offset:]
    '}}'
    >>> exec codeobj
    >>> a
    3
    """

    try:
        codeobj = _compile(source, filename, mode, flags, dont_inherit)
    except SyntaxError as e:
        lines = source.splitlines(True)
        i_line = e.lineno - 1
        offset = e.offset - 1
        lines_body = lines[:i_line]
        lines_rest = lines[i_line:]
        lines_body.append(lines[i_line][:offset])
        lines_rest[0] = lines[i_line][offset:]
        body = ''.join(lines_body)
        rest = ''.join(lines_rest)
        for token in terminators:
            if rest.startswith(token):
                break
        else:
            # The SyntaxError was raised by but terminators.
            raise
        return _compile(body, filename, mode, flags, dont_inherit), len(body)
    else:
        raise ValueError('didn\'t encouter any terminator')


def tokenize(data, pos=0):

    """parse template code and yield name, start, end and data as tuple """

    while pos < len(data):
        for name, stag, etag in tagset:
            if data.startswith(stag, pos):
                try:
                    next = data.index(etag, pos) + len(etag)
                except ValueError:
                    raise TemplateSyntaxError('invalid syntax', len(data))
                expr = data[pos+len(stag):next-len(etag)].strip()
                break
        else:
            name = 'text'
            m = rx_stags.search(data, pos)
            if m:
                next = m.start()
            else:
                next = len(data)
            expr = data[pos:next]
        yield name, pos, next, expr
        pos = next

def parse(data, handler, pos=0):

    """parse template code and call appropriate methods of handler """

    try:
        for name, start, end, expr in tokenize(data, pos):
            method = getattr(handler, 'handle_'+name)
            method(expr)
    except EncodingDetected as err:
        encoding, = err.args
        data_head = data[:end].decode(encoding)
        data_tail = data[end:].decode(encoding)
        pos = len(data_head)
        data = data_head + data_tail
        parse(data, handler, pos)


def main(argv=None, stdout=None):

    if argv is None:
        argv = sys.argv[1:]
    if stdout is None:
        stdout = sys.stdout

    from optparse import OptionParser

    parser = OptionParser('python %prog [options] filenames...')
    parser.add_option('-e', '--execute',
                      help='execute given code before evaluation')
    parser.add_option('-f', '--filename',
                      help='run given Python script before evaluation')
    opts, args = parser.parse_args(argv)

    namespace = {}
    if opts.execute:
        exec(opts.execute, namespace)
    if opts.filename:
        execfile(opts.filename, namespace)
    for filename in args:
        template = Template(file(filename).read())
        result = template.evaluate(namespace)
        encoding = template.encoding or 'utf-8'
        stdout.write(result.encode(encoding))


if __name__ == '__main__':
    main()
