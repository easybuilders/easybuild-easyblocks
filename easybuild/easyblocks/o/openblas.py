"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
from distutils.version import LooseVersion
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.systemtools import POWER, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.build_log import print_warning
from easybuild.tools.config import ERROR
from easybuild.tools.run import run_cmd, check_log_for_errors

TARGET = 'TARGET'


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    @staticmethod
    def extra_options():
        extra_vars = ConfigureMake.extra_options()
        extra_vars.update({
            'build_ilp64': [True, "Also build OpenBLAS with 64-bit integer support", CUSTOM],
            'ilp64_suffix': ['_ilp64', "Symbol (and library name) suffix to use when building with 64-bit integers",
                             CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """ Ensure iterative build if also building with 64-bit integer support """
        super(EB_OpenBLAS, self).__init__(*args, **kwargs)

        if self.cfg['build_ilp64']:
            if not type(self.cfg['buildopts']) is list:
                # ensure iterative build
                self.cfg['buildopts'] = [self.cfg['buildopts'], self.cfg['buildopts']]
            else:
                print_warning("buildopts cannot be a list when 'build_ilp64' is enabled; ignoring 'build_ilp64'")
                self.cfg['build_ilp64'] = False

    def configure_step(self):
        """ set up some options - but no configure command to run"""
        default_opts = {
            'BINARY': '64',
            'CC': os.getenv('CC'),
            'FC': os.getenv('FC'),
            'USE_OPENMP': '1',
            'USE_THREAD': '1',
            'MAKE_NB_JOBS': '-1',  # Disable internal parallelism to let EB choose
        }

        ilp64_opts = {
            'INTERFACE64': '1',
            'SYMBOLSUFFIX': self.cfg['ilp64_suffix'],
        }

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

        all_opts = default_opts.copy()
        if self.iter_idx == 1 and self.cfg['build_ilp64']:
            all_opts.update(ilp64_opts)

        for key in sorted(all_opts.keys()):
            for opts_key in ['buildopts', 'testopts', 'installopts']:
                if '%s=' % key not in self.cfg[opts_key]:
                    self.cfg.update(opts_key, "%s='%s'" % (key, all_opts[key]))

        self.cfg.update('installopts', 'PREFIX=%s' % self.installdir)

    def build_step(self):
        """ Custom build step excluding the tests """

        # Equivalent to `make all` without the tests
        build_parts = ['libs', 'netlib']
        for buildopt in self.cfg['buildopts'].split():
            if 'BUILD_RELAPACK' in buildopt and '1' in buildopt:
                build_parts += ['re_lapack']
        build_parts += ['shared']

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
        """ Mandatory test step plus optional runtest"""

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
        if self.cfg['build_ilp64']:
            custom_paths['files'].extend('lib/libopenblas_%s.%s' % (self.cfg['ilp64_suffix'], x)
                                         for x in ['a', get_shared_lib_ext()])

        super(EB_OpenBLAS, self).sanity_check_step(custom_paths=custom_paths)
