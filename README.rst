.. image:: https://github.com/easybuilders/easybuild/raw/develop/logo/png/easybuild_logo_2022_horizontal_dark_bg_transparent.png
   :align: center
   :height: 400px

.. image:: https://github.com/easybuilders/easybuild-easyblocks/workflows/easyblocks%20unit%20tests/badge.svg?branch=develop

`EasyBuild <https://easybuild.io>`_ is a software build
and installation framework that allows you to manage (scientific) software
on High Performance Computing (HPC) systems in an efficient way.

The **easybuild-easyblocks** package provides a collection of *easyblocks* for
EasyBuild. Easyblocks are Python modules that implement the install procedure for a
(group of) software package(s). Together with the EasyBuild framework,
they allow to easily build and install supported software packages.

The EasyBuild documentation is available at http://docs.easybuild.io/.

The easybuild-easyblocks source code is hosted on GitHub, along
with an issue tracker for bug reports and feature requests, see
https://github.com/easybuilders/easybuild-easyblocks.

Related Python packages:

* **easybuild-framework**

  * the EasyBuild framework, which includes the ``easybuild.framework`` and ``easybuild.tools`` Python
    packages that provide general support for building and installing software
  * GitHub repository: https://github.com/easybuilders/easybuild-framework
  * PyPi: https://pypi.python.org/pypi/easybuild-framework

* **easybuild-easyconfigs**

  * a collection of example easyconfig files that specify which software to build,
    and using which build options; these easyconfigs will be well tested
    with the latest compatible versions of the easybuild-framework and easybuild-easyblocks packages
  * GitHub repository: https://github.com/easybuilders/easybuild-easyconfigs
  * PyPi: https://pypi.python.org/pypi/easybuild-easyconfigs
