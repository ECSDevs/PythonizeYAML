import { defineUserConfig } from 'vuepress'
import { viteBundler } from '@vuepress/bundler-vite'
import { defaultTheme } from '@vuepress/theme-default'

export default defineUserConfig({
  lang: 'en-US',
  title: 'PythonizeYAML',
  description: 'A PyYAML-compatible YAML library with lossless round trips.',
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
    navbar: [
      { text: 'Guides', link: '/guide/' },
      { text: 'API', link: '/api/' },
      { text: 'GitHub', link: 'https://github.com/ECSDevs/PythonizeYAML' }
    ],
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
      ]
    }
  })
})
