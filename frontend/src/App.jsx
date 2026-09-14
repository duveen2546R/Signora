import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Landing from './pages/Landing'
import SignPage from './pages/SignPage'
import Capture from './pages/Capture'
import Watch from './pages/Watch'
import './App.css'

export default function App() {
  const youtubeSigning = import.meta.env.VITE_YOUTUBE_SIGNING !== 'false'
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="sign" element={<SignPage />} />
          <Route path="capture" element={<Capture />} />
          {youtubeSigning && <Route path="watch" element={<Watch />} />}
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
