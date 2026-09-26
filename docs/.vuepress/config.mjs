import { defineUserConfig } from 'vuepress'
import { viteBundler } from '@vuepress/bundler-vite'
import { defaultTheme } from '@vuepress/theme-default'

export default defineUserConfig({
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
          { text: 'Guides', link: '/guide/' },
          { text: 'API', link: '/api/' },
          { text: 'GitHub', link: 'https://github.com/ECSDevs/PythonizeYAML' }
        ]
      },
      '/zh_CN/': {
        selectLanguageName: '简体中文',
        navbar: [
          { text: '指南', link: '/zh_CN/guide/' },
          { text: 'API', link: '/zh_CN/api/' },
          { text: 'GitHub', link: 'https://github.com/ECSDevs/PythonizeYAML' }
        ]
      }
    },
    sidebar: {
      '/guide/': [
        {
          text: 'Guides',
          children: [
            '/guide/',
            '/guide/quickstart',
            '/guide/round-trips',
            '/guide/safety'
          ]
        }
      ],
      '/api/': [
        {
          text: 'API Reference',
          children: ['/api/', '/api/functions', '/api/documents']
        }
      ],
      '/zh_CN/guide/': [
        {
          text: '指南',
          children: [
            '/zh_CN/guide/',
            '/zh_CN/guide/quickstart',
            '/zh_CN/guide/round-trips',
            '/zh_CN/guide/safety'
          ]
        }
      ],
      '/zh_CN/api/': [
        {
          text: 'API 参考',
          children: ['/zh_CN/api/', '/zh_CN/api/functions', '/zh_CN/api/documents']
        }
      ]
    }
  })
})
