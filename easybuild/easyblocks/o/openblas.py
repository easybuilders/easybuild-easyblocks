"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Terje Kvernes (University of Oslo)
"""
import os
import re
from distutils.version import LooseVersion
from easybuild.base import fancylogger
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import ERROR, build_option
from easybuild.tools.filetools import read_file
from easybuild.tools.systemtools import POWER, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.run import run_cmd, check_log_for_errors

_log = fancylogger.getLogger('systemtools', fname=False)

try:
    from archspec import cpu as archspec_cpu
    HAVE_ARCHSPEC = True
except ImportError as err:
    _log.debug("Failed to import 'archspec' Python module: %s", err)
    HAVE_ARCHSPEC = False

TARGET = 'TARGET'


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for OpenBLAS"""
        extra_vars = {
            'targetfile': ['TargetList.txt', "File containing OpenBLAS target list", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def configure_step(self):
        """ set up some options - but no configure command to run"""

        default_opts = {
            'BINARY': '64',
            'CC': os.getenv('CC'),
            'FC': os.getenv('FC'),
            'USE_OPENMP': '1',
            'USE_THREAD': '1',
        }

        # Handle the possibility of setting the target architecture as dynamic,
        # where OpenBLAS will optimize the kernel at runtime.
        self._dynamic_target = False

        compiler_optarch = self._optarch_for_compiler(build_option('optarch'))

        # Retain the (m)arch part of the optarch settings across the entire object.
        self._optarch_architecture = compiler_optarch

        if '%s=' % TARGET in self.cfg['buildopts']:
            # Add any TARGET in buildopts to default_opts, so it is passed to testopts and installopts
            for buildopt in self.cfg['buildopts'].split():
                optpair = buildopt.split('=')
                if optpair[0] == TARGET:
                    default_opts[optpair[0]] = optpair[1]
        elif LooseVersion(self.version) < LooseVersion('0.3.6') and get_cpu_architecture() == POWER:
            # There doesn't seem to be a POWER9 option yet, but POWER8 should work.
            print_warning("OpenBLAS 0.3.5 and lower have known issues on POWER systems")
            default_opts[TARGET] = 'POWER8'
        elif compiler_optarch:
            compiler_family = self.toolchain.comp_family()
            self.log.info("EasyBuild full optarch requested for %s: %s" % (compiler_family, compiler_optarch))
            optarch_as_target = self._parse_optarch(compiler_optarch)
            mapped_target = None

            if optarch_as_target:
                # Note that _parse_optarch returns lowercased results, so GENERIC has become 'generic'.
                if optarch_as_target == 'generic':
                    self._set_dynamic_architecture(default_opts)
                    mapped_target = 'generic'
                else:
                    self.log.info("EasyBuild march: %s" % optarch_as_target)
                    openblas_targets = self._get_openblas_targets(self.cfg['targetfile'])
                    mapped_target = self._get_mapped_target(optarch_as_target, openblas_targets)
            else:
                self.log.info("Optarch specified for %s, but no march detected", compiler_family)

            if mapped_target is None:
                print_warning("optarch for %s given as '%s'\n"
                              "EasyBuild was unable to map this to an equivalent OpenBLAS target!\n"
                              "OpenBLAS will be built to optimize its kernel at runtime!\n"
                              % (self.toolchain.comp_family(), compiler_optarch))
                self.log.warning("Unable to map %s to an OpenBLAS target, falling back to runtime optimization."
                                 % compiler_optarch)
                self._set_dynamic_architecture(default_opts)
            elif mapped_target == 'generic':
                self.log.info("Optarch 'GENERIC' requested, will enable runtime optimization.")
            else:
                mapped_target = mapped_target.upper()
                self.log.info("Optarch mapped between EasyBuild and OpenBLAS to: " + mapped_target)
                default_opts[TARGET] = mapped_target

        for key in sorted(default_opts.keys()):
            for opts_key in ['buildopts', 'testopts', 'installopts']:
                if '%s=' % key not in self.cfg[opts_key]:
                    self.cfg.update(opts_key, "%s='%s'" % (key, default_opts[key]))

        self.cfg.update('installopts', 'PREFIX=%s' % self.installdir)

    def build_step(self):
        """ Custom build step excluding the tests """

        # Equivalent to `make all` without the tests
        build_parts = ['libs', 'netlib']
        for buildopt in self.cfg['buildopts'].split():
            if 'BUILD_RELAPACK' in buildopt and '1' in buildopt:
                build_parts += ['re_lapack']
        build_parts += ['shared']

        # If we're doing either a dynamic build or utilizing optarch,
        # strip march from all environment variables except the EBVAR-prefixed ones.
        # For dynamic builds we should ignore optarch completely and for optarch-set builds
        # we need to adhere to TARGET and not march.
        if self._dynamic_target is True or self._optarch_architecture is True:
            self.log.info('Dynamic build requested, stripping march settings from environment variables')
            for k in os.environ.keys():
                optarch_to_strip = '-' + self._optarch_architecture
                if 'EBVAR' not in k and self._optarch_architecture in os.environ[k]:
                    os.environ[k] = os.environ[k].replace(optarch_to_strip, '')

        # Pass CFLAGS through command line to avoid redefinitions (issue xianyi/OpenBLAS#818)
        cflags = 'CFLAGS'
        if os.environ[cflags]:
            self.cfg.update('buildopts', "%s='%s'" % (cflags, os.environ[cflags]))
            del os.environ[cflags]
            self.log.info("Environment variable %s unset and passed through command line" % cflags)

        makecmd = 'make'
        if self.cfg['parallel']:
            makecmd += ' -j %s' % self.cfg['parallel']

        cmd = ' '.join([self.cfg['prebuildopts'], makecmd, ' '.join(build_parts), self.cfg['buildopts']])
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """ Mandatory test step plus optional runtest """

        run_tests = ['tests']
        if self.cfg['runtest']:
            run_tests += [self.cfg['runtest']]

        for runtest in run_tests:
            cmd = "%s make %s %s" % (self.cfg['pretestopts'], runtest, self.cfg['testopts'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False, regexp=False)

            # Raise an error if any test failed
            check_log_for_errors(out, [('FATAL ERROR', ERROR)])

    def sanity_check_step(self):
        """ Custom sanity check for OpenBLAS """
        custom_paths = {
            'files': ['include/cblas.h', 'include/f77blas.h', 'include/lapacke_config.h', 'include/lapacke.h',
                      'include/lapacke_mangling.h', 'include/lapacke_utils.h', 'include/openblas_config.h',
                      'lib/libopenblas.a', 'lib/libopenblas.%s' % get_shared_lib_ext()],
            'dirs': [],
        }
        super(EB_OpenBLAS, self).sanity_check_step(custom_paths=custom_paths)

    def _optarch_for_compiler(self, optarch):
        """
        Extracts the appropriate optarch for the compiler currently being used.
        If it is not compiler-specific it is returned as-is.
        If no optarch is found, False is returned.
        :param optarch: A complete optarch statement.
        https://easybuild.readthedocs.io/en/latest/Controlling_compiler_optimization_flags.html
        """
        if optarch is False:
            return False

        compiler = self.toolchain.comp_family()
        compiler_specific_optarch_string = ''

        if type(optarch) == str:
            compiler_specific_optarch_string = optarch
        elif type(optarch) == dict:
            if compiler in optarch:
                compiler_specific_optarch_string = optarch[compiler]
        else:
            raise EasyBuildError("optarch in an unexpected format: '%s'" % type(optarch)).__class__.__name__

        return compiler_specific_optarch_string

    def _parse_optarch(self, compiler_optarch):
        """
        Pick the march out of a given optarch.
        Note that the result is lowercased.
        :param compiler_optarch: An optarch for a given compiler.
        https://easybuild.readthedocs.io/en/latest/Controlling_compiler_optimization_flags.html
        """

        target_arch = ''
        pieces = compiler_optarch.split()

        for piece in pieces:
            spec = piece.split('=')
            if spec[0] == 'march' or spec[0] == '-march':
                target_arch = spec[1]

        return target_arch.lower()

    def _get_openblas_targets(self, targetfile):
        """
        Parse the openblas target file and generate a list of targets.
        :param targetfile: A file with OpenBLAS targets.
        """
        targets = []

        if os.path.isfile(targetfile):
            # Assumption, the OpenBLAS TargetList.txt has one target per line and that
            # single words on a line is a target if they match a simple regexp...
            re_target = re.compile(r'^[A-Z0-9_]+$')
            for line in read_file(targetfile).splitlines():
                match = re_target.match(line)
                if match is not None:
                    targets.append(line.strip().lower())
        else:
            print_warning("Unable to find OpenBLAS targetfile '%s'" % os.path.realpath(targetfile))

        return targets

    def _set_dynamic_architecture(self, default_opts):
        """
        Sets the DYNAMIC_ARCH option for OpenBLAS, building a library that chooses
        an optimized kernel at runtime. Also removes any previous TARGET setting, if any.
        """
        default_opts['DYNAMIC_ARCH'] = 1
        default_opts.pop(TARGET, None)
        self._dynamic_target = True

    def _get_mapped_target(self, march, openblas_targets):
        """
        Attempts to match the given march in the list of openblas targets.
        If archspec is installed, will try to match directly or follow ancestors for
        architectures that will work.
        Returns None if no target was found.
        """

        result = None

        if HAVE_ARCHSPEC:
            self.log.info("Using archspec to match optarch to openblas targets.")

            openblas_arch = set(['alpha', 'arm', 'ia64', 'mips', 'mips64',
                                 'power', 'sparc', 'zarch'])
            openblas_arch_map = {
                'amd64': 'x86_64',
                'powerpc64': 'power',
                'i386': 'x86',
                'aarch64': 'arm64',
            }
            openblas_arch.update(openblas_arch_map.keys())
            openblas_arch.update(openblas_arch_map.values())

            skylake = set(["skylake"])
            available_targets = set(openblas_targets) | skylake | openblas_arch

            try:
                uarch = archspec_cpu.TARGETS[march]
            except KeyError:
                warning_string = "Archspec was asked to find '" + march + "' as an architecture, but failed!"
                print_warning(warning_string)
                self.log.warning(warning_string)
                return None

            if uarch.name in available_targets:
                result = uarch.name
            else:
                self.log.info("No direct match for '" + march + "' between archspec and OpenBLAS, traversing ancestry.")
                for uarch in uarch.ancestors:
                    if uarch.name in available_targets:
                        self.log.info("Ancestral match between '" + march + "' and '" + uarch.name + "'.")
                        result = uarch.name
                        break

            # Skylake for OpenBLAS is called 'skylakex'. Handle this exception exceptionally.
            if result == 'skylake':
                result = 'skylakex'

        else:
            self.log.info("Unable to find archspec, optarch matching will be poor.")
            if march == 'skylake':
                result = 'skylakex'
            elif march in openblas_targets:
                result = march

        return result
