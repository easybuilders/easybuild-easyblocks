##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for wxPython, implemented as an easyblock

@author: Balazs Hajgato (Vrije Universiteit Brussel)
@author: Kenneth Hoste (HPC-UGent)
@author: Maxime Boissonneault (Compute Canada, Calcul Quebec, Universite Laval)
"""
import glob
import os

from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_python_version
from easybuild.tools.filetools import change_dir, symlink
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_wxPython(PythonPackage):
    """Support for installing the wxPython Python package."""

    def build_step(self):
        """Custom build step for wxPython."""
        if LooseVersion(self.version) >= LooseVersion("4"):
            prebuild_opts = self.cfg['prebuildopts']
            script = 'build.py'
            self.wxflag = ''
            if get_software_root('wxWidgets'):
                self.wxflag = '--use_syswx'

            BUILD_CMD = "%(prebuild_opts)s %(pycmd)s %(script)s --prefix=%(prefix)s -v"
            base_cmd = BUILD_CMD % {
                'prebuild_opts': prebuild_opts,
                'pycmd': self.python_cmd,
                'script': script,
                'prefix': self.installdir,
            }

            # Do we need to build wxWidgets internally?
            if self.wxflag == '':
                cmd = base_cmd + " build_wx"
                run_cmd(cmd, log_all=True, simple=True)

            cmd = base_cmd + " %s build_py" % self.wxflag
            run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """Custom install procedure for wxPython."""
        # wxPython configure, build, and install with one script
        preinst_opts = self.cfg['preinstallopts']
        INSTALL_CMD = "%(preinst_opts)s %(pycmd)s %(script)s --prefix=%(prefix)s"
        if LooseVersion(self.version) >= LooseVersion("4"):
            script = 'build.py'
            cmd = INSTALL_CMD % {
                'preinst_opts': preinst_opts,
                'pycmd': self.python_cmd,
                'script': script,
                'prefix': self.installdir,
            }
            # install fails and attempts to install in the python module. building the wheel, and then installing it
            cmd = cmd + " %s -v bdist_wheel" % self.wxflag
            run_cmd(cmd, log_all=True, simple=True)

            # get whether it is 35, 36, 37, 38, etc.
            pyver = det_python_version(self.python_cmd)
            pyver = pyver[0] + pyver[2]

            cmd = "pip install --no-deps --prefix=%(prefix)s dist/wxPython-%(version)s-cp%(pyver)s*.whl" % {
                'prefix': self.installdir,
                'version': self.version,
                'pyver': pyver
            }
        else:
            script = os.path.join('wxPython', 'build-wxpython.py')
            cmd = INSTALL_CMD % {
                'preinst_opts': preinst_opts,
                'pycmd': self.python_cmd,
                'script': script,
                'prefix': self.installdir,
            }
            cmd = cmd + " --wxpy_installdir=%s --install" % self.installdir

        run_cmd(cmd, log_all=True, simple=True)

        # add symbolic links for libwx_*so.* files
        # (which are created automatically by 'build.py install', but not by 'pip install *.whl')
        if LooseVersion(self.version) >= LooseVersion("4"):
            wx_lib_dir = os.path.join(self.installdir, self.pylibdir, 'wx')
            cwd = change_dir(wx_lib_dir)
            lib_so_files = glob.glob('libwx*.so.*')
            for lib_so_file in lib_so_files:
                symlink(lib_so_file, lib_so_file[:-2])
            change_dir(cwd)

    def sanity_check_step(self):
        """Custom sanity check for wxPython."""
        majver = '.'.join(self.version.split('.')[:2])
        shlib_ext = get_shared_lib_ext()
        py_bins = ['crust', 'shell', 'wxrc']
        files = []
        dirs = []
        if LooseVersion(self.version) < LooseVersion("4"):
            files.extend([os.path.join('bin', 'wxrc')])
            dirs.extend(['include', 'share'])
            py_bins.extend(['alacarte', 'alamode', 'wrap'])
        elif LooseVersion(self.version) >= LooseVersion("4.2"):
            majver = '3.2'  # this is 3.2 in ver 4.2.x
            py_bins.extend(['slices', 'slicesshell'])
        elif LooseVersion(self.version) >= LooseVersion("4.1"):
            majver = '3.1'  # this is 3.1 in ver 4.1.x
            py_bins.extend(['slices', 'slicesshell'])
        elif LooseVersion(self.version) >= LooseVersion("4.0"):
            majver = '3.0'  # for some reason this is still 3.0 in ver 4.0.x
            py_bins.extend(['slices', 'slicesshell'])

        files.extend([os.path.join('bin', 'py%s' % x) for x in py_bins])
        dirs.extend([self.pylibdir])

        if LooseVersion(self.version) < LooseVersion("4"):
            libfiles = ['lib%s-%s.%s' % (x, majver, shlib_ext) for x in ['wx_baseu', 'wx_gtk2u_core']]
            files.extend([os.path.join('lib', f) for f in libfiles])
        else:
            if not get_software_root('wxWidgets'):
                libfiles = ['lib%s-%s.%s' % (x, majver, shlib_ext) for x in ['wx_baseu', 'wx_gtk3u_core']]
                files.extend([os.path.join(self.pylibdir, 'wx', f) for f in libfiles])

        custom_paths = {
            'files': files,
            'dirs': dirs,
        }

        # test using 'import wx' (i.e. don't use 'import wxPython')
        self.options['modulename'] = 'wx'

        if LooseVersion(self.version) < LooseVersion("4"):
            # also test importing wxversion
            custom_commands = [(self.python_cmd, '-c "import wxversion"')]
        else:
            # also test importing wx.lib.wxcairo
            custom_commands = [(self.python_cmd, '-c "import wx.lib.wxcairo"')]

        return super(EB_wxPython, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Custom update for $PYTHONPATH for wxPython."""
        txt = super(EB_wxPython, self).make_module_extra()

        if LooseVersion(self.version) < LooseVersion("4"):
            # make sure that correct subdir is also included to $PYTHONPATH
            majver = '.'.join(self.version.split('.')[:2])
            txt += self.module_generator.prepend_paths('PYTHONPATH', os.path.join(self.pylibdir, 'wx-%s-gtk2' % majver))

        return txt
