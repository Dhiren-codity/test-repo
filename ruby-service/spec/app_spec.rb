# frozen_string_literal: true

require 'spec_helper'

# frozen_string_literal: true

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'uses detect_language based on file path for python service call' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts "hi"'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts "hi"'))
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: 'puts "hi"', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'GET /status' do
    it 'returns status for all services when healthy' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8080').and_return({ status: 'healthy' })
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8081').and_return({ status: 'healthy' })

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('healthy')
    end

    it 'handles unreachable services gracefully' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8080').and_return({ status: 'unreachable', error: 'timeout' })
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8081').and_return({ status: 'healthy' })

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['go']['status']).to eq('unreachable')
      expect(json_response['services']['go']['error']).to eq('timeout')
      expect(json_response['services']['python']['status']).to eq('healthy')
    end
  end

  describe 'POST /diff' do
    it 'returns diff and new code review on success' do
      old_content = "puts 'old'"
      new_content = "puts 'new'"
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: old_content, new_content: new_content))
        .and_return({ 'changes' => 1, 'diff' => "+ puts 'new'\n- puts 'old'" })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: new_content))
        .and_return({ 'score' => 75.5, 'issues' => [] })

      post '/diff', { old_content: old_content, new_content: new_content }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to include('changes' => 1)
      expect(json_response['new_code_review']).to include('score' => 75.5)
    end

    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'only one' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns metrics, review, and overall_quality on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code here'))
        .and_return({ 'complexity' => 3 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code here'))
        .and_return({ 'score' => 92.0, 'issues' => [] })
      allow_any_instance_of(PolyglotAPI).to receive(:calculate_quality_score)
        .and_return(88.88)

      post '/metrics', { content: 'code here' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']).to include('complexity' => 3)
      expect(json_response['review']).to include('score' => 92.0)
      expect(json_response['overall_quality']).to eq(88.88)
    end

    it 'returns 0.0 overall_quality when metrics has error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'bad'))
        .and_return({ 'error' => 'boom' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'bad'))
        .and_return({ 'score' => 50.0, 'issues' => ['x'] })

      post '/metrics', { content: 'bad' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns dashboard statistics and summary' do
      files = [{ 'path' => 'a.rb', 'content' => "puts 'a'" }]
      go_stats = { 'total_files' => 1, 'total_lines' => 1, 'languages' => { 'ruby' => 1 } }
      py_stats = { 'average_score' => 80.0, 'total_issues' => 0 }

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return(go_stats)
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return(py_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:calculate_dashboard_health_score).and_return(77.77)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('timestamp')
      expect(json_response['file_statistics']).to eq(go_stats)
      expect(json_response['review_statistics']).to eq(py_stats)
      expect(json_response['summary']).to include(
        'total_files' => 1,
        'total_lines' => 1,
        'languages' => { 'ruby' => 1 },
        'average_quality_score' => 80.0,
        'total_issues' => 0,
        'health_score' => 77.77
      )
    end

    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end
  end
end
