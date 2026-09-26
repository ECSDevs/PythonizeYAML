import { defineUserConfig } from 'vuepress'
import { viteBundler } from '@vuepress/bundler-vite'
import { defaultTheme } from '@vuepress/theme-default'

export default defineUserConfig({
  base: '/PythonizeYAML/',
  locales: {
    '/': {
      lang: 'en-US',
      title: 'PythonizeYAML',
      description: 'A PyYAML-compatible YAML library with lossless round trips.'
    },
    '/zh_CN/': {
      lang: 'zh-CN',
      title: 'PythonizeYAML',
      description: '兼容 PyYAML、支持无损往返的 YAML 库。'
    }
  },
  bundler: viteBundler({
    viteOptions: {
      css: {
        preprocessorOptions: {
          scss: { api: 'legacy' }
        }
      }
    }
  }),
  theme: defaultTheme({
    logo: null,
    locales: {
      '/': {
        selectLanguageName: 'English',
        navbar: [
          { text: 'Tutorial', link: '/guide/' },
          { text: 'API', link: '/api/' },
          { text: 'GitHub', link: 'https://github.com/ECSDevs/PythonizeYAML' }
        ]
      },
      '/zh_CN/': {
        selectLanguageName: '简体中文',
        navbar: [
          { text: '教程', link: '/zh_CN/guide/' },
          { text: 'API', link: '/zh_CN/api/' },
          { text: 'GitHub', link: 'https://github.com/ECSDevs/PythonizeYAML' }
        ]
      }
    },
    sidebar: {
      '/guide/': [
        {
          text: 'Tutorial',
          children: [
            '/guide/',
            '/guide/basics',
            '/guide/editing',
            '/guide/styles',
            '/guide/safety'
          ]
        },
        {
          text: 'Worked examples',
          children: ['/guide/quickstart', '/guide/round-trips']
        }
      ],
      '/api/': [
        {
          text: 'API Reference',
          children: [
            '/api/',
            '/api/functions',
            '/api/documents',
            '/api/styles',
            '/api/errors'
          ]
        }
      ],
      '/zh_CN/guide/': [
        {
          text: '教程',
          children: [
            '/zh_CN/guide/',
            '/zh_CN/guide/basics',
            '/zh_CN/guide/editing',
            '/zh_CN/guide/styles',
            '/zh_CN/guide/safety'
          ]
        },
        {
          text: '实战示例',
          children: ['/zh_CN/guide/quickstart', '/zh_CN/guide/round-trips']
        }
      ],
      '/zh_CN/api/': [
        {
          text: 'API 参考',
          children: [
            '/zh_CN/api/',
            '/zh_CN/api/functions',
            '/zh_CN/api/documents',
            '/zh_CN/api/styles',
            '/zh_CN/api/errors'
          ]
        }
      ]
    }
  })
})
