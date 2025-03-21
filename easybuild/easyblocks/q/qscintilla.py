##
# Copyright 2009-2025 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing QScintilla, implemented as an easyblock

author: Kenneth Hoste (HPC-UGent)
author: Maxime Boissonneault (Compute Canada)
"""
import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, mkdir, symlink, write_file, find_glob_pattern
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_QScintilla(ConfigureMake):
    """Support for building/installing QScintilla."""

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment for building & installing QScintilla."""

        super(EB_QScintilla, self).prepare_step(*args, **kwargs)

        pyqt5 = get_software_root('PyQt5')
        pyqt = get_software_root('PyQt')
        qt5 = get_software_root('Qt5')
        if pyqt5:
            self.pyqt_root = pyqt5
            self.pyqt_pkg_name = "PyQt5"
        elif pyqt:
            self.pyqt_root = pyqt
            self.pyqt_pkg_name = "PyQt4"
        elif qt5:
            self.pyqt_root = qt5
            self.pyqt_pkg_name = "PyQt5"
        else:
            raise EasyBuildError("Failed to determine PyQt(5) installation prefix. Missing PyQt(5) dependency?")

        # PyQt5 is supported by QScintilla from version 2.11, otherwise there are some additional hacks/patches needed
        if LooseVersion(self.version) < LooseVersion('2.11') and pyqt5:
            raise EasyBuildError("PyQt5 is supported by QScintilla in version 2.11 and greater.")

    def configure_step(self):
        """Custom configuration procedure for QScintilla."""

        srcdir = os.path.join(self.cfg['start_dir'], 'Qt4Qt5')
        try:
            os.chdir(srcdir)
        except OSError as err:
            raise EasyBuildError("Failed to change to %s: %s", srcdir, err)

        # replace template values for install locations in qscintilla.pro configuration file
        regex_subs = [
            (r'\$\$\[QT_HOST_DATA\]', os.path.join(self.installdir, 'data')),
            (r'\$\$\[QT_INSTALL_DATA\]', os.path.join(self.installdir, 'data')),
            (r'\$\$\[QT_INSTALL_HEADERS\]', os.path.join(self.installdir, 'include')),
            (r'\$\$\[QT_INSTALL_LIBS\]', os.path.join(self.installdir, 'lib')),
            (r'\$\$\[QT_INSTALL_TRANSLATIONS\]', os.path.join(self.installdir, 'trans')),
        ]
        apply_regex_substitutions('qscintilla.pro', regex_subs)

        run_shell_cmd("qmake qscintilla.pro")

    def build_step(self):
        """Custom build procedure for QScintilla."""

        # make sure that $CXXFLAGS is being passed down
        self.cfg.update('buildopts', r'CXXFLAGS="$CXXFLAGS \$(DEFINES)"')

        super(EB_QScintilla, self).build_step()

    def install_step(self):
        """Custom install procedure for QScintilla."""

        super(EB_QScintilla, self).install_step()

        # also install Python bindings if Python is included as a dependency
        python = get_software_root('Python')
        if python:
            pydir = os.path.join(self.cfg['start_dir'], 'Python')
            try:
                os.chdir(pydir)
            except OSError as err:
                raise EasyBuildError("Failed to change to %s: %s", pydir, err)

            # apparently this directory has to be there
            qsci_sipdir = os.path.join(self.installdir, 'share', 'sip', self.pyqt_pkg_name)
            mkdir(qsci_sipdir, parents=True)

            pylibdir = os.path.join(det_pylibdir(), self.pyqt_pkg_name)
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])

            sip_incdir = find_glob_pattern(os.path.join(self.pyqt_root, 'include', 'python%s*' % pyshortver), False)
            # depending on PyQt5 versions and how it was installed, the sip directory could be in various places
            # test them and figure out the first one that matches
            pyqt_sip_subdir = [os.path.join('share', 'python%s*' % pyshortver, 'site-packages', 'sip',
                                            self.pyqt_pkg_name),
                               os.path.join('share', 'sip', self.pyqt_pkg_name),
                               os.path.join('share', 'sip'),
                               os.path.join('lib', 'python%s*' % pyshortver, 'site-packages', self.pyqt_pkg_name,
                                            'bindings')
                               ]
            pyqt_sipdir_options = [os.path.join(self.pyqt_root, subdir) for subdir in pyqt_sip_subdir]
            for pyqt_sipdir_option in pyqt_sipdir_options:
                pyqt_sipdir = find_glob_pattern(pyqt_sipdir_option, False)
                if pyqt_sipdir:
                    break

            if not pyqt_sipdir:
                raise EasyBuildError("Failed to find PyQt5 sip directory")

            cfgopts = [
                '--destdir %s' % os.path.join(self.installdir, pylibdir),
                '--qsci-sipdir %s' % qsci_sipdir,
                '--qsci-incdir %s' % os.path.join(self.installdir, 'include'),
                '--qsci-libdir %s' % os.path.join(self.installdir, 'lib'),
                '--pyqt-sipdir %s' % pyqt_sipdir,
                '--apidir %s' % os.path.join(self.installdir, 'qsci', 'api', 'python'),
                '--no-stubs',
            ]
            if sip_incdir:
                cfgopts += ['--sip-incdir %s' % sip_incdir]

            if LooseVersion(self.version) >= LooseVersion('2.10.7'):
                cfgopts.append('--no-dist-info')

            # This flag was added in version 2.11
            if LooseVersion(self.version) >= LooseVersion('2.11'):
                cfgopts.append("--pyqt=%s" % self.pyqt_pkg_name)

            run_shell_cmd("python configure.py %s" % ' '.join(cfgopts))

            super(EB_QScintilla, self).build_step()
            super(EB_QScintilla, self).install_step()

            target_dir = os.path.join(self.installdir, pylibdir)
            pyqt_pylibdir = os.path.join(self.pyqt_root, pylibdir)
            try:
                os.chdir(target_dir)
                for entry in [x for x in os.listdir(pyqt_pylibdir) if not x.startswith('__init__.py')]:
                    symlink(os.path.join(pyqt_pylibdir, entry), os.path.join(target_dir, entry))
            except OSError as err:
                raise EasyBuildError("Failed to symlink PyQt Python bindings in %s: %s", target_dir, err)

            # also requires empty __init__.py file to ensure Python modules can be imported from this location
            write_file(os.path.join(target_dir, '__init__.py'), '')

    def sanity_check_step(self):
        """Custom sanity check for QScintilla."""

        if LooseVersion(self.version) >= LooseVersion('2.10'):
            if self.pyqt_pkg_name == 'PyQt5':
                qsci_lib = 'libqscintilla2_qt5'
            else:
                qsci_lib = 'libqscintilla2_qt4'
        else:
            qsci_lib = 'libqscintilla2'

        custom_paths = {
            'files': [os.path.join('lib', qsci_lib + '.' + get_shared_lib_ext())],
            'dirs': ['data', os.path.join('include', 'Qsci'), 'trans'],
        }
        # also install Python bindings if Python is included as a dependency
        python = get_software_root('Python')

        custom_commands = []
        if python:
            custom_paths['dirs'].extend([
                os.path.join(det_pylibdir(), self.pyqt_pkg_name),
                os.path.join('qsci', 'api', 'python'),
                os.path.join('share', 'sip', self.pyqt_pkg_name),
            ])
            custom_commands.append("python -s -c 'import %s.Qsci'" % self.pyqt_pkg_name)

        super(EB_QScintilla, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
