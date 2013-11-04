# Copyright 2012 Jussi Pakkanen

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import coredata
import environment
import dependencies
import copy, os

class InvalidArguments(coredata.MesonException):
    pass

class Build:
    """A class that holds the status of one build including
    all dependencies and so on.
    """

    def __init__(self, environment):
        self.environment = environment
        self.project = None
        self.targets = {}
        self.compilers = []
        self.cross_compilers = []
        self.global_args = {}
        self.tests = []
        self.headers = []
        self.man = []
        self.data = []
        self.static_linker = None
        self.static_cross_linker = None
        self.configure_files = []
        self.pot = []

    def add_compiler(self, compiler):
        if len(self.compilers) == 0:
            self.static_linker = self.environment.detect_static_linker(compiler)
        self.compilers.append(compiler)

    def add_cross_compiler(self, compiler):
        if len(self.cross_compilers) == 0:
            self.static_cross_linker = self.environment.detect_static_linker(compiler)
        self.cross_compilers.append(compiler)

    def get_project(self):
        return self.project

    def get_targets(self):
        return self.targets

    def get_tests(self):
        return self.tests

    def get_headers(self):
        return self.headers

    def get_man(self):
        return self.man

    def get_data(self):
        return self.data

    def get_configure_files(self):
        return self.configure_files

    def get_global_flags(self, compiler):
        return self.global_args.get(compiler.get_language(), [])

class IncludeDirs():
    def __init__(self, curdir, dirs, kwargs):
        self.curdir = curdir
        self.incdirs = dirs
        # Fixme: check that the directories actually exist.
        # Also that they don't contain ".." or somesuch.
        if len(kwargs) > 0:
            raise InvalidArguments('Includedirs function does not take keyword arguments.')

    def get_curdir(self):
        return self.curdir

    def get_incdirs(self):
        return self.incdirs

class BuildTarget():
    def __init__(self, name, subdir, is_cross, sources, objects, environment, kwargs):
        self.name = name
        self.subdir = subdir
        self.is_cross = is_cross
        self.sources = []
        self.objects = []
        self.external_deps = []
        self.include_dirs = []
        self.link_targets = []
        self.filename = 'no_name'
        self.need_install = False
        self.pch = {}
        self.extra_args = {}
        self.generated = []
        self.process_sourcelist(sources)
        self.process_objectlist(objects)
        self.process_kwargs(kwargs)
        if len(self.sources) == 0 and len(self.generated) == 0:
            raise InvalidArguments('Build target %s has no sources.' % name)

    def process_objectlist(self, objects):
        assert(isinstance(objects, list))
        for s in objects:
            if isinstance(s, str):
                self.objects.append(s)
            else:
                raise InvalidArguments('Bad object in target %s.' % self.name)

    def process_sourcelist(self, sources):
        if not isinstance(sources, list):
            sources = [sources]
        for s in sources:
            # Holder unpacking. Ugly.
            if hasattr(s, 'glist'):
                s = s.glist
            if isinstance(s, str):
                self.sources.append(s)
            elif isinstance(s, GeneratedList):
                self.generated.append(s)
            else:
                raise InvalidArguments('Bad source in target %s.' % self.name)

    def get_original_kwargs(self):
        return self.kwargs

    def copy_kwargs(self, kwargs):
        self.kwargs = copy.copy(kwargs)
        # This sucks quite badly. Arguments
        # are holders but they can't be pickled
        # so unpack those known.
        if 'deps' in self.kwargs:
            d = self.kwargs['deps']
            if not isinstance(d, list):
                d = [d]
            newd = []
            for i in d:
                if hasattr(i, 'el'):
                    newd.append(i.el)
                else:
                    newd.append(i)
            self.kwargs['deps'] = newd

    def get_rpaths(self):
        return self.get_transitive_rpaths()

    def get_transitive_rpaths(self):
        result = []
        for i in self.link_targets:
            result += i.get_rpaths()
        return result

    def process_kwargs(self, kwargs):
        self.copy_kwargs(kwargs)
        kwargs.get('modules', [])
        self.need_install = kwargs.get('install', self.need_install)
        llist = kwargs.get('link_with', [])
        if not isinstance(llist, list):
            llist = [llist]
        for linktarget in llist:
            # Sorry for this hack. Keyword targets are kept in holders
            # in kwargs. Unpack here without looking at the exact type.
            if hasattr(linktarget, "target"):
                linktarget = linktarget.target
            self.link(linktarget)
        c_pchlist = kwargs.get('c_pch', [])
        if not isinstance(c_pchlist, list):
            c_pchlist = [c_pchlist]
        self.add_pch('c', c_pchlist)
        cpp_pchlist = kwargs.get('cpp_pch', [])
        if not isinstance(cpp_pchlist, list):
            cpp_pchlist = [cpp_pchlist]
        self.add_pch('cpp', cpp_pchlist)
        clist = kwargs.get('c_args', [])
        if not isinstance(clist, list):
            clist = [clist]
        self.add_compiler_args('c', clist)
        cpplist = kwargs.get('cpp_args', [])
        if not isinstance(cpplist, list):
            cpplist = [cpplist]
        self.add_compiler_args('cpp', cpplist)
        if 'version' in kwargs:
            self.set_version(kwargs['version'])
        if 'soversion' in kwargs:
            self.set_soversion(kwargs['soversion'])
        inclist = kwargs.get('include_dirs', [])
        if not isinstance(inclist, list):
            inclist = [inclist]
        self.add_include_dirs(inclist)
        deplist = kwargs.get('deps', [])
        if not isinstance(deplist, list):
            deplist = [deplist]
        self.add_external_deps(deplist)

    def get_subdir(self):
        return self.subdir

    def get_filename(self):
        return self.filename

    def get_extra_args(self, language):
        return self.extra_args.get(language, [])

    def get_dependencies(self):
        return self.link_targets

    def get_basename(self):
        return self.name

    def get_source_subdir(self):
        return self.subdir

    def get_sources(self):
        return self.sources

    def get_objects(self):
        return self.objects

    def get_generated_sources(self):
        return self.generated

    def should_install(self):
        return self.need_install

    def has_pch(self):
        return len(self.pch) > 0

    def get_pch(self, language):
        try:
            return self.pch[language]
        except KeyError:
            return[]

    def get_include_dirs(self):
        return self.include_dirs

    def add_external_deps(self, deps):
        for dep in deps:
            if hasattr(dep, 'el'):
                dep = dep.el
            if not isinstance(dep, dependencies.Dependency):
                raise InvalidArguments('Argument is not an external dependency')
            self.external_deps.append(dep)
            if isinstance(dep, dependencies.Dependency):
                self.process_sourcelist(dep.get_sources())

    def get_external_deps(self):
        return self.external_deps

    def add_dep(self, args):
        [self.add_external_dep(dep) for dep in args]

    def link(self, target):
        if not isinstance(target, StaticLibrary) and \
        not isinstance(target, SharedLibrary):
            print(target)
            raise InvalidArguments('Link target is not library.')
        self.link_targets.append(target)

    def set_generated(self, genlist):
        for g in genlist:
            if not(isinstance(g, GeneratedList)):
                raise InvalidArguments('Generated source argument is not the output of a generator.')
            self.generated.append(g)

    def add_pch(self, language, pchlist):
        if len(pchlist) == 0:
            return
        if len(pchlist) == 2:
            if environment.is_header(pchlist[0]):
                if not environment.is_source(pchlist[1]):
                    raise InvalidArguments('PCH definition must contain one header and at most one source.')
            elif environment.is_source(pchlist[0]):
                if not environment.is_header(pchlist[1]):
                    raise InvalidArguments('PCH definition must contain one header and at most one source.')
                pchlist = [pchlist[1], pchlist[0]]
            else:
                raise InvalidArguments('PCH argument %s is of unknown type.' % pchlist[0])
        elif len(pchlist) > 2:
            raise InvalidArguments('PCH definition may have a maximum of 2 files.')
        self.pch[language] = pchlist

    def add_include_dirs(self, args):
        ids = []
        for a in args:
            # FIXME same hack, forcibly unpack from holder.
            if hasattr(a, 'includedirs'):
                a = a.includedirs
            if not isinstance(a, IncludeDirs):
                raise InvalidArguments('Include directory to be added is not an include directory object.')
            ids.append(a)
        self.include_dirs += ids

    def add_compiler_args(self, language, flags):
        for a in flags:
            if not isinstance(a, str):
                raise InvalidArguments('A non-string passed to compiler args.')
        if language in self.extra_args:
            self.extra_args[language] += flags
        else:
            self.extra_args[language] = flags

    def get_aliaslist(self):
        return []


class Generator():
    def __init__(self, args, kwargs):
        if len(args) != 1:
            raise InvalidArguments('Generator requires one and only one positional argument')
        
        if hasattr(args[0], 'target'):
            exe = args[0].target
            if not isinstance(exe, Executable):
                raise InvalidArguments('First generator argument must be an executable.')
        elif hasattr(args[0], 'ep'):
            exe = args[0].ep
        else:
            print(args[0])
            raise InvalidArguments('First generator argument must be an executable object.')
        self.exe = exe
        self.process_kwargs(kwargs)

    def get_exe(self):
        return self.exe

    def process_kwargs(self, kwargs):
        if 'arguments' not in kwargs:
            raise InvalidArguments('Generator must have "arguments" keyword argument.')
        args = kwargs['arguments']
        if isinstance(args, str):
            args = [args]
        if not isinstance(args, list):
            raise InvalidArguments('"Arguments" keyword argument must be a string or a list of strings.')
        for a in args:
            if not isinstance(a, str):
                raise InvalidArguments('A non-string object in "arguments" keyword argument.')
        self.arglist = args
        
        if 'outputs' not in kwargs:
            raise InvalidArguments('Generator must have "outputs" keyword argument.')
        outputs = kwargs['outputs']
        if not isinstance(outputs, list):
            outputs = [outputs]
        for rule in outputs:
            if not isinstance(rule, str):
                raise InvalidArguments('"outputs" may only contain strings.')
            if not '@BASENAME@' in rule and not '@PLAINNAME@' in rule:
                raise InvalidArguments('"outputs" must contain @BASENAME@ or @PLAINNAME@.')
            if '/' in rule or '\\' in rule:
                raise InvalidArguments('"outputs" must not contain a directory separator.')
        self.outputs = outputs

    def get_base_outnames(self, inname):
        plainname = os.path.split(inname)[1]
        basename = plainname.split('.')[0]
        return [x.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname) for x in self.outputs]

    def get_arglist(self):
        return self.arglist

class GeneratedList():
    def __init__(self, generator):
        if hasattr(generator, 'generator'):
            generator = generator.generator
        self.generator = generator
        self.infilelist = []
        self.outfilelist = []
        self.outmap = {}

    def add_file(self, newfile):
        self.infilelist.append(newfile)
        outfiles = self.generator.get_base_outnames(newfile)
        self.outfilelist += outfiles
        self.outmap[newfile] = outfiles

    def get_infilelist(self):
        return self.infilelist

    def get_outfilelist(self):
        return self.outfilelist

    def get_outputs_for(self, filename):
        return self.outmap[filename]

    def get_generator(self):
        return self.generator

class Executable(BuildTarget):
    def __init__(self, name, subdir, is_cross, sources, objects, environment, kwargs):
        super().__init__(name, subdir, is_cross, sources, objects, environment, kwargs)
        suffix = environment.get_exe_suffix()
        if suffix != '':
            self.filename = self.name + '.' + suffix
        else:
            self.filename = self.name


class StaticLibrary(BuildTarget):
    def __init__(self, name, subdir, is_cross, sources, objects, environment, kwargs):
        super().__init__(name, subdir, is_cross, sources, objects, environment, kwargs)
        prefix = environment.get_static_lib_prefix()
        suffix = environment.get_static_lib_suffix()
        self.filename = prefix + self.name + '.' + suffix

class SharedLibrary(BuildTarget):
    def __init__(self, name, subdir, is_cross, sources, objects, environment, kwargs):
        self.version = None
        self.soversion = None
        super().__init__(name, subdir, is_cross, sources, environment, kwargs);
        self.prefix = environment.get_shared_lib_prefix()
        self.suffix = environment.get_shared_lib_suffix()

    def get_shbase(self):
        return self.prefix + self.name + '.' + self.suffix

    def get_rpaths(self):
        return [self.subdir] + self.get_transitive_rpaths()

    def get_filename(self):
        fname = self.get_shbase()
        if self.version is None:
            return fname
        else:
            return fname + '.' + self.version

    def set_version(self, version):
        if not isinstance(version, str):
            print(version)
            raise InvalidArguments('Shared library version is not a string.')
        self.version = version

    def set_soversion(self, version):
        if isinstance(version, int):
            version = str(version)
        if not isinstance(version, str):
            raise InvalidArguments('Shared library soversion is not a string or integer.')
        self.soversion = version

    def get_aliaslist(self):
        aliases = []
        if self.soversion is not None:
            aliases.append(self.get_shbase() + '.' + self.soversion)
        if self.version is not None:
            aliases.append(self.get_shbase())
        return aliases

class ConfigureFile():

    def __init__(self, subdir, sourcename, targetname, configuration_data):
        self.subdir = subdir
        self.sourcename = sourcename
        self.targetname = targetname
        self.configuration_data = configuration_data

    def get_configuration_data(self):
        return self.configuration_data

    def get_sources(self):
        return self.sources
    
    def get_subdir(self):
        return self.subdir

    def get_source_name(self):
        return self.sourcename

    def get_target_name(self):
        return self.targetname

class ConfigurationData():
    def __init__(self):
        super().__init__()
        self.values = {}

    def get(self, name):
        return self.values[name]

    def keys(self):
        return self.values.keys()
