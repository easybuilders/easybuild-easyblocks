##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2013-2024 CaSToRC, The Cyprus Institute
# Authors::   George Tsouloupas <g.tsouloupas@cyi.ac.cy>
# License::   MIT/GPL
# $Id$
#
##
"""
Easybuild support for building NAMD, implemented as an easyblock

@author: George Tsouloupas (Cyprus Institute)
@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import re
import shutil
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, extract_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class EB_NAMD(MakeCp):
    """
    Support for building NAMD
    """
    @staticmethod
    def extra_options():
        """Define extra NAMD-specific easyconfig parameters."""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        extra.update({
            # see http://charm.cs.illinois.edu/manuals/html/charm++/A.html
            'charm_arch': [None, "Charm++ target architecture", MANDATORY],
            'charm_extra_cxxflags': ['', "Extra C++ compiler options to use for building Charm++", CUSTOM],
            'charm_opts': ['--with-production', "Charm++ build options", CUSTOM],
            'cuda': [None, "Enable CUDA build if CUDA is among the dependencies", CUSTOM],
            'namd_basearch': [None, "NAMD base target architecture (compiler family is appended)", CUSTOM],
            'namd_cfg_opts': ['', "NAMD configure options", CUSTOM],
            'runtest': [True, "Run NAMD test case after building", CUSTOM],
        })

        return extra

    def __init__(self, *args, **kwargs):
        """Custom easyblock constructor for NAMD, initialize class variables."""
        super(EB_NAMD, self).__init__(*args, **kwargs)
        self.namd_arch = None

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""
        super(EB_NAMD, self).prepare_step(*args, **kwargs)

        if self.cfg['namd_basearch'] is None:

            self.log.info("namd_basearch not specified, so determining it based a CPU arch...")

            arch = get_cpu_architecture()
            if arch == X86_64:
                basearch = 'Linux-x86_64'
            elif arch == POWER:
                basearch = 'Linux-POWER'

            self.cfg['namd_basearch'] = basearch
            self.log.info("Derived value for 'namd_basearch': %s", self.cfg['namd_basearch'])

    def extract_step(self):
        """Custom extract step for NAMD, we need to extract charm++ so we can patch it."""
        super(EB_NAMD, self).extract_step()

        change_dir(self.src[0]['finalpath'])
        self.charm_tarballs = glob.glob('charm-*.tar')
        if len(self.charm_tarballs) != 1:
            raise EasyBuildError("Expected to find exactly one tarball for Charm++, found: %s", self.charm_tarballs)

        srcdir = extract_file(self.charm_tarballs[0], os.getcwd(), change_into_dir=False)
        change_dir(srcdir)

    def patch_step(self, *args, **kwargs):
        """Patch scripts to avoid using hardcoded /bin/csh."""
        super(EB_NAMD, self).patch_step(*args, **kwargs)

        self.charm_dir = self.charm_tarballs[0][:-4]

        charm_config = os.path.join(self.charm_dir, 'src', 'scripts', 'configure')
        apply_regex_substitutions(charm_config, [(r'SHELL=/bin/csh', 'SHELL=$(which csh)')])

        for csh_script in [os.path.join('plugins', 'import_tree'), os.path.join('psfgen', 'import_tree'),
                           os.path.join(self.charm_dir, 'src', 'QuickThreads', 'time', 'raw')]:
            if os.path.exists(csh_script):
                apply_regex_substitutions(csh_script, [(r'^#!\s*/bin/csh\s*$', '#!/usr/bin/env csh')])

    def configure_step(self):
        """Custom configure step for NAMD, we build charm++ first (if required)."""

        # complete Charm ++ and NAMD architecture string with compiler family
        comp_fam = self.toolchain.comp_family()
        if self.toolchain.options.get('usempi', False):
            charm_arch_comp = 'mpicxx'
        else:
            charm_arch_comps = {
                toolchain.GCC: 'gcc',
                toolchain.INTELCOMP: 'icc',
            }
            charm_arch_comp = charm_arch_comps.get(comp_fam, None)
        namd_comps = {
            toolchain.GCC: 'g++',
            toolchain.INTELCOMP: 'icc',
        }
        namd_comp = namd_comps.get(comp_fam, None)
        if charm_arch_comp is None or namd_comp is None:
            raise EasyBuildError("Unknown compiler family, can't complete Charm++/NAMD target architecture.")

        # NOTE: important to add smp BEFORE the compiler
        # charm arch style is: mpi-linux-x86_64-smp-mpicxx
        # otherwise the setting of name_charm_arch below will get things
        # in the wrong order
        if self.toolchain.options.get('openmp', False):
            self.cfg.update('charm_arch', 'smp')
        self.cfg.update('charm_arch', charm_arch_comp)
        self.log.info("Updated 'charm_arch': %s", self.cfg['charm_arch'])

        self.namd_arch = '%s-%s' % (self.cfg['namd_basearch'], namd_comp)
        self.log.info("Completed NAMD target architecture: %s", self.namd_arch)

        cmd = "./build charm++ %(arch)s %(opts)s --with-numa -j%(parallel)s '%(cxxflags)s'" % {
            'arch': self.cfg['charm_arch'],
            'cxxflags': os.environ['CXXFLAGS'] + ' -DMPICH_IGNORE_CXX_SEEK ' + self.cfg['charm_extra_cxxflags'],
            'opts': self.cfg['charm_opts'],
            'parallel': self.cfg['parallel'],
        }
        charm_subdir = '.'.join(os.path.basename(self.charm_tarballs[0]).split('.')[:-1])
        self.log.debug("Building Charm++ using cmd '%s' in '%s'" % (cmd, charm_subdir))
        run_cmd(cmd, path=charm_subdir)

        # compiler (options)
        self.cfg.update('namd_cfg_opts', '--cc "%s" --cc-opts "%s"' % (os.environ['CC'], os.environ['CFLAGS']))
        cxxflags = os.environ['CXXFLAGS']
        if LooseVersion(self.version) >= LooseVersion('2.12'):
            cxxflags += ' --std=c++11'
        self.cfg.update('namd_cfg_opts', '--cxx "%s" --cxx-opts "%s"' % (os.environ['CXX'], cxxflags))

        # NAMD dependencies: CUDA, TCL, FFTW
        cuda = get_software_root('CUDA')
        if cuda and (self.cfg['cuda'] is None or self.cfg['cuda']):
            self.cfg.update('namd_cfg_opts', "--with-cuda --cuda-prefix %s" % cuda)
        elif not self.cfg['cuda']:
            self.log.warning("CUDA is disabled")
        elif not cuda and self.cfg['cuda']:
            raise EasyBuildError("CUDA is not a dependency, but support for CUDA is enabled.")

        tcl = get_software_root('Tcl')
        if tcl:
            self.cfg.update('namd_cfg_opts', '--with-tcl --tcl-prefix %s' % tcl)
            tclversion = '.'.join(get_software_version('Tcl').split('.')[0:2])
            tclv_subs = [(r'-ltcl[\d.]*\s', '-ltcl%s ' % tclversion)]

            apply_regex_substitutions(os.path.join('arch', '%s.tcl' % self.cfg['namd_basearch']), tclv_subs)

        fftw = get_software_root('FFTW')
        if fftw:
            if LooseVersion(get_software_version('FFTW')) >= LooseVersion('3.0'):
                if LooseVersion(self.version) >= LooseVersion('2.9'):
                    self.cfg.update('namd_cfg_opts', "--with-fftw3")
                else:
                    raise EasyBuildError("Using FFTW v3.x only supported in NAMD v2.9 and up.")
            else:
                self.cfg.update('namd_cfg_opts', "--with-fftw")
            self.cfg.update('namd_cfg_opts', "--fftw-prefix %s" % fftw)

        namd_charm_arch = "--charm-arch %s" % '-'.join(self.cfg['charm_arch'].strip().split())
        cmd = "./config %s %s %s " % (self.namd_arch, namd_charm_arch, self.cfg["namd_cfg_opts"])
        run_cmd(cmd)

    def build_step(self):
        """Build NAMD for configured architecture"""
        super(EB_NAMD, self).build_step(path=self.namd_arch)

    def test_step(self):
        """Run NAMD test case."""
        if self.cfg['runtest']:

            if not build_option('mpi_tests'):
                self.log.info("Skipping testing of NAMD since MPI testing is disabled")
                return

            namdcmd = os.path.join(self.cfg['start_dir'], self.namd_arch, 'namd%s' % self.version.split('.')[0])
            if self.cfg['charm_arch'].startswith('mpi'):
                namdcmd = self.toolchain.mpi_cmd_for(namdcmd, 2)
            ppn = ''
            if self.toolchain.options.get('openmp', False):
                ppn = '+ppn 2'
            cmd = "%(pretestopts)s %(namd)s %(ppn)s %(testopts)s %(testdir)s" % {
                'namd': namdcmd,
                'ppn': ppn,
                'pretestopts': self.cfg['pretestopts'],
                'testdir': os.path.join(self.cfg['start_dir'], self.namd_arch, 'src', 'alanin'),
                'testopts': self.cfg['testopts'],
            }
            out, ec = run_cmd(cmd, simple=False)
            if ec == 0:
                test_ok_regex = re.compile(r"(^Program finished.$|End of program\s*$)", re.M)
                if test_ok_regex.search(out):
                    self.log.debug("Test '%s' ran fine." % cmd)
                else:
                    raise EasyBuildError("Test '%s' failed ('%s' not found), output: %s",
                                         cmd, test_ok_regex.pattern, out)
        else:
            self.log.debug("Skipping running NAMD test case after building")

    def install_step(self):
        """Install by copying the correct directory to the install dir"""
        srcdir = os.path.join(self.cfg['start_dir'], self.namd_arch)
        try:
            # copy all files, except for .rootdir (required to avoid cyclic copying)
            for item in [x for x in os.listdir(srcdir) if x not in ['.rootdir']]:
                fullsrc = os.path.join(srcdir, item)
                if os.path.isdir(fullsrc):
                    shutil.copytree(fullsrc, os.path.join(self.installdir, item), symlinks=False)
                elif os.path.isfile(fullsrc):
                    shutil.copy2(fullsrc, self.installdir)
        except OSError as err:
            raise EasyBuildError("Failed to copy NAMD build from %s to install directory: %s", srcdir, err)

    def make_module_extra(self):
        """Add the install directory to PATH"""
        txt = super(EB_NAMD, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PATH", [''])
        return txt

    def sanity_check_step(self):
        """Custom sanity check for NAMD."""
        custom_paths = {
            'files': ['charmrun', 'flipbinpdb', 'flipdcd', 'namd%s' % self.version.split('.')[0], 'psfgen'],
            'dirs': ['inc'],
        }
        super(EB_NAMD, self).sanity_check_step(custom_paths=custom_paths)
