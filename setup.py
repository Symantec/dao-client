import setuptools
import sys


install_requires = ['pyzmq','netaddr']

if sys.version[0] == 2 and sys.version[1] <= 6:
    install_requires.append('argparse')


setuptools.setup(
    name='dao.client',
    version='0.5.9',
    namespace_packages=['dao'],
    author='Sergii Kashaba, Ruslan Kiyanchuk',
    description='Deployment Automation and Orchestration Framework Client',
    classifiers=[
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English'
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
    ],
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    tests_require=['pytest'],
    entry_points={'console_scripts': ['dao = dao.client.shell:run']},
    data_files=[('/etc/dao', ['etc/client.cfg', 'etc/client-logger.cfg'])]
)
