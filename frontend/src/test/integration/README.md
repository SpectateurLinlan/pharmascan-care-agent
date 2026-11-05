# 跨功能组件回归

这里使用 Vitest、React Testing Library 和 synthetic HTTP/Auth 替身，验证 App、导航、
首次体验及跨页面确认。文件包括 PatientApp、PatientExperience、PatientNavigation、Session045 的测试。

它们不是浏览器 e2e，也不证明真实数据库、provider 或设备可用。
单业务测试与其实现就近放置；共享数据放 ../fixtures。
